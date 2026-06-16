from __future__ import annotations

import json
import mimetypes
import hashlib
import re
from itertools import combinations
from math import prod
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .config import WEB_DIR, ensure_dirs
from .aicai_client import fetch_aicai_worldcup_context, snapshots_for_match
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
        if parsed.path == "/api/matches/select":
            self.handle_select_matches()
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
        aicai_context = safe_fetch_aicai_context(matches)
        for match in matches:
            if target_id and match["match_id"] != target_id:
                continue
            snapshots = fetch_odds(match)
            snapshots.extend(snapshots_for_match(match, aicai_context.get("match_contexts", {}).get(match["match_id"])))
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
        aicai_context = safe_fetch_aicai_context(load_matches())
        aicai_fixtures = aicai_context.get("fixtures", [])
        fixtures = merge_fixtures(fixtures, [*sporttery_fixtures, *aicai_fixtures])
        for fixture in fixtures:
            self.store.upsert_fixture(fixture)
        split = split_fixtures(fixtures)
        standings, standings_meta = fetch_bing_standings()
        self.send_json(
            {
                "ok": True,
                "meta": meta,
                "sporttery_meta": sporttery_meta,
                "aicai_meta": {
                    "source": aicai_context.get("source"),
                    "count": aicai_context.get("count", 0),
                    "error": aicai_context.get("error"),
                },
                "standings_meta": standings_meta,
                "scheduled": split["scheduled"],
                "finished": split["finished"],
                "standings": standings,
                "state": self.build_state(),
            }
        )

    def handle_select_matches(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
        mode = payload.get("mode") or "single"
        fixtures, _meta = fetch_public_schedule()
        sporttery_fixtures, _sporttery_meta = fetch_sporttery_fixtures()
        aicai_context = safe_fetch_aicai_context(load_matches())
        fixtures = merge_fixtures(fixtures, [*sporttery_fixtures, *aicai_context.get("fixtures", [])])
        for fixture in fixtures:
            self.store.upsert_fixture(fixture)
        selected_fixture = find_fixture_for_payload(fixtures, payload)
        selected = select_fixture_window(fixtures, selected_fixture, limit=4 if mode == "next4" else 1)
        if not selected:
            self.send_json({"ok": False, "error": "未找到可加入预测的赛程，请先刷新赛程。", "state": self.build_state()}, status=404)
            return
        matches = [match_from_fixture(fixture) for fixture in selected]
        save_matches(matches)
        sync_matches(self.store, matches)
        fresh_aicai_context = safe_fetch_aicai_context(matches)
        refreshed = []
        for match in matches:
            snapshots = fetch_odds(match)
            snapshots.extend(snapshots_for_match(match, fresh_aicai_context.get("match_contexts", {}).get(match["match_id"])))
            inserted = self.store.insert_snapshots(match["match_id"], snapshots)
            refreshed.append({"match_id": match["match_id"], "inserted": inserted})
        self.send_json(
            {
                "ok": True,
                "selected": [match["match_id"] for match in matches],
                "refreshed": refreshed,
                "message": "已更新预测比赛并刷新数据",
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
            and row.get("recommendation_role") != "anti_scoreline_value"
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
            exposure = combo_exposure_profile(combo)
            risk_score = min(100, max_risk + risk_penalty + exposure["penalty"])
            has_negative_leg = any(item["leg"]["ev"] <= 0 for item in combo)
            if has_negative_leg:
                decision = "禁止串关"
                reason = "组合含负EV腿"
            elif exposure.get("has_repeated_hot_favorite") and size >= 3:
                decision = "高风险观察"
                reason = exposure["reason"] or "多场热门方向重复，不能当核心串关"
            elif ev < 0.05:
                decision = "观察"
                reason = "组合EV不足5%"
            elif risk_score > 75:
                decision = "高风险观察"
                reason = exposure["reason"] or "组合风险偏高"
            else:
                decision = "可小注"
                reason = exposure["reason"] or "单腿正EV且组合EV达标"
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
                    "exposure": exposure,
                    "decision": decision,
                    "reason": reason,
                }
            )
    return sorted(combos, key=lambda row: (row["decision"] == "可小注", row["ev"]), reverse=True)[:24]


def leg_risk_tags(item: dict) -> set[str]:
    leg = item["leg"]
    tags = {f"match:{item['match_id']}", f"play:{leg.get('play_type')}"}
    selection = str(leg.get("selection", ""))
    play_type = str(leg.get("play_type", ""))
    if play_type == "让球胜平负":
        if selection == "让胜":
            tags.add("theme:favorite_cover")
        elif selection == "让平":
            tags.add("theme:one_goal_margin")
        elif selection == "让负":
            tags.add("theme:favorite_not_cover")
    if play_type == "胜平负":
        if selection in {"胜", "负"}:
            tags.add("theme:winner")
            if float(leg.get("model_prob") or 0) >= 0.52:
                tags.add("theme:popular_winner")
        elif selection == "平":
            tags.add("theme:draw")
    role = str(leg.get("recommendation_role", ""))
    if role in {"favorite_tail_hedge", "low_total_protection", "draw_low_score_protection"}:
        tags.add(f"theme:{role}")
    if leg.get("risk_score", 0) >= 60:
        tags.add("risk:high_leg")
    return tags


def combo_exposure_profile(combo: tuple[dict, ...]) -> dict:
    tag_counts: dict[str, int] = {}
    for item in combo:
        for tag in leg_risk_tags(item):
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
    repeated_themes = {
        tag: count
        for tag, count in tag_counts.items()
        if tag.startswith("theme:") and count >= 2
    }
    high_legs = sum(1 for item in combo if item["leg"].get("risk_score", 0) >= 60)
    penalty = 0
    if repeated_themes:
        penalty += min(26, sum((count - 1) * 7 for count in repeated_themes.values()))
    if high_legs >= 2:
        penalty += 8
    if any(tag in repeated_themes for tag in {"theme:favorite_cover", "theme:popular_winner"}):
        penalty += 8
    reason = ""
    if repeated_themes:
        names = ", ".join(tag.split(":", 1)[1] for tag in repeated_themes)
        reason = f"串关共用风险主题：{names}"
    elif high_legs >= 2:
        reason = "组合含多个高风险腿"
    return {
        "penalty": penalty,
        "repeated_themes": repeated_themes,
        "has_repeated_hot_favorite": any(tag in repeated_themes for tag in {"theme:favorite_cover", "theme:popular_winner"}),
        "high_risk_legs": high_legs,
        "reason": reason,
    }


def merge_fixtures(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    for fixture in [*primary, *secondary]:
        key = fixture_key(fixture) or fixture.get("match_id")
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


def fixture_lookup_key(fixture: dict) -> str:
    kickoff = str(fixture.get("kickoff") or "")
    date = kickoff[:10] if kickoff else ""
    return "|".join(
        str(fixture.get(key) or "").strip().lower().replace(" ", "")
        for key in ("home_team", "away_team")
    ) + f"|{date}"


def find_fixture_for_payload(fixtures: list[dict], payload: dict) -> dict | None:
    match_id = payload.get("match_id")
    fixture_key_value = payload.get("fixture_key")
    if match_id:
        exact = next((fixture for fixture in fixtures if fixture.get("match_id") == match_id), None)
        if exact:
            return exact
    if fixture_key_value:
        exact = next((fixture for fixture in fixtures if fixture_lookup_key(fixture) == fixture_key_value), None)
        if exact:
            return exact
    fixture = payload.get("fixture") or {}
    if fixture:
        key = fixture_lookup_key(fixture)
        return next((item for item in fixtures if fixture_lookup_key(item) == key), None)
    return None


def fixture_quality(fixture: dict) -> int:
    source = str(fixture.get("source") or "")
    if source.startswith("爱彩") or fixture.get("aicai_match_id"):
        return 5
    if source.startswith("中国体彩") or fixture.get("selling_pools") or fixture.get("sporttery_match_num"):
        return 4
    if any(option.get("play") == "胜平负" for option in fixture.get("odds_summary", []) or []):
        return 3
    if re.search(r"T(0[1-9]|1\d|2[0-3]):", str(fixture.get("kickoff") or "")):
        return 2
    return 1


def select_fixture_window(fixtures: list[dict], selected_fixture: dict | None, limit: int) -> list[dict]:
    scheduled = [fixture for fixture in fixtures if fixture.get("status") != "finished"]
    scheduled = [fixture for fixture in scheduled if fixture.get("home_team") and fixture.get("away_team") and fixture.get("kickoff")]
    scheduled.sort(key=lambda fixture: (str(fixture.get("kickoff") or ""), -fixture_quality(fixture)))
    if not selected_fixture:
        selected_fixture = next((fixture for fixture in scheduled if fixture_quality(fixture) >= 3), scheduled[0] if scheduled else None)
    if not selected_fixture:
        return []
    start = str(selected_fixture.get("kickoff") or "")
    candidates = [fixture for fixture in scheduled if str(fixture.get("kickoff") or "") >= start]
    candidates.sort(key=lambda fixture: (str(fixture.get("kickoff") or ""), -fixture_quality(fixture)))
    selected: list[dict] = []
    seen: set[str] = set()

    # The user clicked this exact fixture. Keep it even when it is only a
    # public schedule row without official SP; otherwise the UI appears to do
    # nothing or jumps to the next high-quality fixture.
    selected_key = fixture_lookup_key(selected_fixture)
    selected.append(selected_fixture)
    seen.add(selected_key)
    if len(selected) >= limit:
        return selected

    for fixture in candidates:
        key = fixture_lookup_key(fixture)
        if key in seen:
            continue
        selected.append(fixture)
        seen.add(key)
        if len(selected) >= limit:
            return selected
    for fixture in candidates:
        key = fixture_lookup_key(fixture)
        if key in seen:
            continue
        selected.append(fixture)
        seen.add(key)
        if len(selected) >= limit:
            break
    return selected


def parse_handicap_from_fixture(fixture: dict) -> int | None:
    for row in fixture.get("odds_summary", []) or []:
        play = str(row.get("play") or "")
        match = re.search(r"让球\(([+-]?\d+(?:\.\d+)?)\)", play)
        if match:
            try:
                return int(float(match.group(1)))
            except ValueError:
                return None
    return None


def parse_total_line_from_fixture(fixture: dict) -> float | None:
    for row in fixture.get("aicai_odds_summary", []) or []:
        play = str(row.get("play") or "")
        match = re.search(r"大小球\((\d+(?:\.\d+)?)\)", play)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def parse_h2h_odds_from_fixture(fixture: dict) -> dict | None:
    for source_key in ("odds_summary", "aicai_odds_summary"):
        for row in fixture.get(source_key, []) or []:
            play = str(row.get("play") or "")
            if play not in {"胜平负", "爱彩欧赔"}:
                continue
            values = {}
            for option in row.get("options", []) or []:
                name = str(option.get("name") or "")
                key = {"胜": "home", "平": "draw", "负": "away"}.get(name)
                if not key:
                    continue
                try:
                    values[key] = float(option.get("sp"))
                except (TypeError, ValueError):
                    pass
            if {"home", "draw", "away"} <= set(values):
                return values
    return None


def elo_from_rank(rank: str | int | None) -> int:
    try:
        value = int(rank)
    except (TypeError, ValueError):
        return 1800
    return max(1450, min(2120, 2070 - value * 5))


def implied_probs(odds: dict | None) -> dict | None:
    if not odds:
        return None
    inv = {key: 1 / value for key, value in odds.items() if value and value > 1}
    total = sum(inv.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in inv.items()}


def expected_goals_from_fixture(fixture: dict, odds: dict | None) -> dict:
    total = parse_total_line_from_fixture(fixture) or 2.4
    probs = implied_probs(odds) or {"home": 0.38, "draw": 0.28, "away": 0.34}
    edge = probs.get("home", 0.38) - probs.get("away", 0.34)
    home_share = max(0.25, min(0.75, 0.5 + edge * 0.55))
    home = max(0.35, total * home_share)
    away = max(0.35, total - home)
    return {"home": round(home, 2), "away": round(away, 2)}


def auto_match_id(fixture: dict) -> str:
    source_id = str(fixture.get("match_id") or "")
    if source_id and source_id.startswith("AICAI_"):
        return source_id
    seed = fixture_lookup_key(fixture) or fixture_key(fixture) or source_id
    return "AUTO_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10].upper()


def match_from_fixture(fixture: dict) -> dict:
    odds = parse_h2h_odds_from_fixture(fixture)
    ranks = fixture.get("aicai_rank") or {}
    home_team = fixture.get("home_team") or "主队"
    away_team = fixture.get("away_team") or "客队"
    match = {
        "match_id": auto_match_id(fixture),
        "home_team": home_team,
        "away_team": away_team,
        "home_aliases": [home_team],
        "away_aliases": [away_team],
        "kickoff": fixture.get("kickoff"),
        "stage": fixture.get("sporttery_match_num") or fixture.get("stage") or "世界杯",
        "neutral": True,
        "home_elo": elo_from_rank(ranks.get("home")),
        "away_elo": elo_from_rank(ranks.get("away")),
        "expected_goals": expected_goals_from_fixture(fixture, odds),
        "lineup_status": "unknown",
        "injury_notes": "自动从赛程加入，首发和伤停需赛前复核。",
        "tactical_notes": "自动建模：先使用市场倍率、球队排名和盘口作为底盘；战术细节需后续补充。",
        "weather_notes": "待确认",
        "referee_notes": "待确认",
        "upset_triggers": {
            "underdog_low_block": True,
            "underdog_set_piece": True,
            "early_event_risk": True,
        },
    }
    if odds:
        match["manual_odds"] = odds
    handicap = parse_handicap_from_fixture(fixture)
    if handicap is not None:
        match["sporttery_handicap"] = handicap
    return match


def safe_fetch_aicai_context(matches: list[dict]) -> dict:
    try:
        return fetch_aicai_worldcup_context(matches)
    except Exception as exc:
        return {"source": "https://live.aicai.com/league/index.htm?leagueId=1999&tab=4", "fixtures": [], "match_contexts": {}, "count": 0, "error": str(exc)}


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
