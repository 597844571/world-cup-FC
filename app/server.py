from __future__ import annotations

import json
import mimetypes
from itertools import combinations
from math import prod
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import WEB_DIR, ensure_dirs
from .backtest import evaluate_fixture, summarize_backtests
from .match_registry import find_match, load_matches, save_matches, sync_matches
from .odds_client import fetch_odds
from .odds_store import OddsStore
from .prediction_engine import build_prediction
from .process_client import fetch_match_process, merge_match_process
from .schedule_client import fetch_public_schedule, fetch_sporttery_fixtures, split_fixtures
from .source_registry import load_source_health, load_sources
from .standings_client import fetch_bing_standings, load_standings


class DashboardServer(BaseHTTPRequestHandler):
    store = OddsStore()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            self.send_json(self.build_state())
            return
        if parsed.path.startswith("/api/match/"):
            match_id = parsed.path.rsplit("/", 1)[-1]
            match = find_match(load_matches(), match_id)
            if not match:
                self.send_json({"error": "match not found"}, status=404)
                return
            self.send_json(build_prediction(match, self.store.odds_history(match_id)))
            return
        if parsed.path == "/api/fixtures":
            query = parse_qs(parsed.query)
            status = query.get("status", [None])[0]
            self.send_json({"fixtures": self.store.fixtures(status)})
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/refresh":
            self.handle_refresh()
            return
        if parsed.path == "/api/schedule/query":
            self.handle_schedule_query()
            return
        if parsed.path == "/api/predictions/archive":
            self.handle_archive_predictions()
            return
        if parsed.path == "/api/backtest/run":
            self.handle_backtest()
            return
        else:
            self.send_json({"error": "not found"}, status=404)
            return
    def handle_refresh(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
        matches = load_matches()
        sync_matches(self.store, matches)
        target_id = payload.get("match_id")
        refreshed = []
        process_changed = False
        for match in matches:
            if target_id and match["match_id"] != target_id:
                continue
            snapshots = fetch_odds(match)
            inserted = self.store.insert_snapshots(match["match_id"], snapshots)
            process_payload = fetch_match_process(match)
            enriched, changed = merge_match_process(match, process_payload)
            if changed:
                match.update(enriched)
                process_changed = True
            refreshed.append(
                {
                    "match_id": match["match_id"],
                    "inserted": inserted,
                    "process_source": process_payload.get("source") if process_payload else None,
                    "process_metrics": sum(len(v or {}) for v in (process_payload or {}).get("stats", {}).values()),
                }
            )
        if process_changed:
            save_matches(matches)
        self.send_json({"ok": True, "refreshed": refreshed, "state": self.build_state()})

    def handle_schedule_query(self) -> None:
        fixtures, meta = fetch_public_schedule()
        sporttery_fixtures, sporttery_meta = fetch_sporttery_fixtures()
        fixtures = merge_fixtures(fixtures, sporttery_fixtures)
        for fixture in fixtures:
            self.store.upsert_fixture(fixture)
        split = split_fixtures(fixtures)
        standings, standings_meta = fetch_bing_standings()
        self.send_json(
            {
                "ok": True,
                "meta": meta,
                "sporttery_meta": sporttery_meta,
                "standings_meta": standings_meta,
                "scheduled": split["scheduled"],
                "finished": split["finished"],
                "standings": standings,
                "state": self.build_state(),
            }
        )

    def handle_archive_predictions(self) -> None:
        matches = load_matches()
        sync_matches(self.store, matches)
        archived = []
        for match in matches:
            prediction = build_prediction(match, self.store.odds_history(match["match_id"]))
            count = self.store.archive_prediction(match["match_id"], prediction)
            archived.append({"match_id": match["match_id"], "snapshots": count})
        self.send_json({"ok": True, "archived": archived, "state": self.build_state()})

    def handle_backtest(self) -> None:
        finished = self.store.fixtures("finished")
        inserted = 0
        evaluated = []
        for fixture in finished:
            snapshots = self.store.prediction_snapshots(fixture["match_id"])
            rows = evaluate_fixture(fixture, snapshots, self.store.odds_history(fixture["match_id"]))
            inserted += self.store.insert_backtest_results(rows)
            if rows:
                evaluated.append({"match_id": fixture["match_id"], "results": len(rows)})
        self.send_json({"ok": True, "inserted": inserted, "evaluated": evaluated, "state": self.build_state()})

    def build_state(self) -> dict:
        ensure_dirs()
        matches = load_matches()
        sync_matches(self.store, matches)
        details = []
        for match in matches:
            history = self.store.odds_history(match["match_id"])
            prediction = build_prediction(match, history)
            details.append(
                {
                    "match_id": match["match_id"],
                    "home_team": match["home_team"],
                    "away_team": match["away_team"],
                    "home_aliases": match.get("home_aliases", []),
                    "away_aliases": match.get("away_aliases", []),
                    "kickoff": match.get("kickoff"),
                    "stage": match.get("stage", ""),
                    "sporttery_handicap": match.get("sporttery_handicap"),
                    "expected_goals": match.get("expected_goals"),
                    "lineup_status": match.get("lineup_status"),
                    "injury_notes": match.get("injury_notes"),
                    "tactical_notes": match.get("tactical_notes"),
                    "weather_notes": match.get("weather_notes"),
                    "referee_notes": match.get("referee_notes"),
                    "latest_snapshot": self.store.latest_snapshot_time(match["match_id"]),
                    "prediction": prediction,
                    "odds_history": history,
                }
            )
        backtests = self.store.backtest_results()
        return {
            "matches": details,
            "sporttery_combos": build_sporttery_combos(details),
            "sources": load_sources(),
            "source_health": load_source_health(),
            "fixtures": {
                "scheduled": self.store.fixtures("scheduled"),
                "finished": self.store.fixtures("finished"),
            },
            "standings": load_standings(),
            "prediction_snapshots": self.store.prediction_snapshots(),
            "backtests": backtests,
            "backtest_summary": summarize_backtests(backtests),
        }

    def serve_static(self, request_path: str) -> None:
        if request_path in {"", "/"}:
            request_path = "/index.html"
        target = (WEB_DIR / request_path.lstrip("/")).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.exists() or target.is_dir():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def build_sporttery_combos(details: list[dict]) -> list[dict]:
    legs_by_match = []
    for item in details:
        candidates = item["prediction"].get("sporttery", {}).get("candidate_pool", [])
        usable = [
            row
            for row in candidates
            if row.get("sp")
            and row.get("ev") is not None
            and row["ev"] > 0
            and row.get("play_type") not in {"比分", "半全场"}
            and row.get("decision") in {"可小注", "观察", "高风险观察"}
            and row.get("allup_allowed", True)
        ]
        if usable:
            best = sorted(
                usable,
                key=lambda row: (
                    row.get("mapping_priority", 0),
                    row["decision"] == "可小注",
                    row["risk_adjusted_score"],
                    row["ev"],
                ),
                reverse=True,
            )[0]
            legs_by_match.append(
                {
                    "match_id": item["match_id"],
                    "match": f"{item['home_team']} vs {item['away_team']}",
                    "leg": best,
                }
            )
    combos = []
    max_size = min(4, len(legs_by_match))
    for size in range(2, max_size + 1):
        for idx, combo in enumerate(combinations(legs_by_match, size), start=1):
            probability = prod(item["leg"]["model_prob"] for item in combo)
            sp = prod(item["leg"]["sp"] for item in combo)
            ev = probability * sp - 1
            max_risk = max(item["leg"]["risk_score"] for item in combo)
            risk_penalty = 8 if size >= 3 else 0
            risk_score = min(100, max_risk + risk_penalty)
            has_negative_leg = any(item["leg"]["ev"] <= 0 for item in combo)
            if has_negative_leg:
                decision = "禁止串关"
                reason = "组合含负EV腿"
            elif ev < 0.05:
                decision = "观察"
                reason = "组合EV不足5%"
            elif risk_score > 75:
                decision = "高风险观察"
                reason = "组合风险偏高"
            else:
                decision = "可小注"
                reason = "单腿正EV且组合EV达标"
            combos.append(
                {
                    "combo_id": f"C{size}-{idx}",
                    "type": f"{size}串1",
                    "legs": [
                        {
                            "match_id": item["match_id"],
                            "match": item["match"],
                            "play_type": item["leg"]["play_type"],
                            "selection": item["leg"]["selection"],
                            "sp": item["leg"]["sp"],
                            "model_prob": item["leg"]["model_prob"],
                            "ev": item["leg"]["ev"],
                        }
                        for item in combo
                    ],
                    "probability": round(probability, 4),
                    "sp": round(sp, 3),
                    "ev": round(ev, 4),
                    "risk_score": risk_score,
                    "decision": decision,
                    "reason": reason,
                }
            )
    return sorted(combos, key=lambda row: (row["decision"] == "可小注", row["ev"]), reverse=True)[:24]


def merge_fixtures(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for fixture in [*primary, *secondary]:
        key = fixture.get("match_id") or fixture_key(fixture)
        if key in merged:
            merged[key].update({k: v for k, v in fixture.items() if v not in (None, "", [])})
        else:
            merged[key] = dict(fixture)
    return sorted(merged.values(), key=lambda row: row.get("kickoff") or "")


def fixture_key(fixture: dict) -> str:
    return "|".join(
        str(fixture.get(key) or "").strip().lower()
        for key in ("home_team", "away_team", "kickoff")
    )


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), DashboardServer)
    print(f"World Cup Prediction Terminal running at http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    run(args.host, args.port)
