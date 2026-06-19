from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any

from .aicai_client import fetch_aicai_worldcup_context, snapshots_for_match
from .config import REFRESH_STATUS_PATH, SERVERLESS_PREDICTION_SNAPSHOTS_PATH, load_json
from .match_registry import load_matches
from .prediction_engine import build_prediction
from .schedule_client import fetch_public_schedule, fetch_sporttery_fixtures, split_fixtures
from .source_registry import load_sources
from .standings_client import load_standings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(value: str) -> str:
    return re.sub(r"[\s　]+", "", value or "").lower()


def names_for(match: dict[str, Any], side: str) -> set[str]:
    prefix = "home" if side == "home" else "away"
    names = {match.get(f"{prefix}_team", ""), *match.get(f"{prefix}_aliases", [])}
    return {normalize_name(str(name)) for name in names if name}


def fixture_matches(match: dict[str, Any], fixture: dict[str, Any]) -> bool:
    home_names = names_for(match, "home")
    away_names = names_for(match, "away")
    fixture_home = normalize_name(fixture.get("home_team", ""))
    fixture_away = normalize_name(fixture.get("away_team", ""))
    return fixture_home in home_names and fixture_away in away_names


def sporttery_history(match: dict[str, Any], fixtures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fixture = next((item for item in fixtures if fixture_matches(match, item)), None)
    if not fixture:
        return []
    raw = fixture.get("raw_json") or {}
    captured_at = utc_now()
    source = "sporttery_official_match_list"
    rows: list[dict[str, Any]] = []

    for pool in raw.get("poolList", []) or []:
        code = str(pool.get("poolCode", "")).upper()
        if not code:
            continue
        for market, key in (
            ("sporttery_pool_open", "cbtValue"),
            ("sporttery_pool_single", "cbtSingle"),
            ("sporttery_pool_allup", "cbtAllUp"),
        ):
            rows.append(
                {
                    "match_id": match["match_id"],
                    "captured_at": captured_at,
                    "source": source,
                    "bookmaker": "中国体育彩票",
                    "market": market,
                    "selection": code,
                    "odds_decimal": float(pool.get(key, 0) or 0),
                }
            )

    for item in raw.get("oddsList", []) or []:
        pool_code = str(item.get("poolCode", "")).upper()
        if pool_code == "HAD":
            for key, selection, model_selection in (("h", "胜", "home"), ("d", "平", "draw"), ("a", "负", "away")):
                append_odd(rows, match, captured_at, source, "胜平负", selection, item.get(key))
                append_odd(rows, match, captured_at, source, "h2h", model_selection, item.get(key))
        elif pool_code == "HHAD":
            line = item.get("goalLine")
            if line not in {None, ""}:
                rows.append(
                    {
                        "match_id": match["match_id"],
                        "captured_at": captured_at,
                        "source": source,
                        "bookmaker": "中国体育彩票",
                        "market": "sporttery_handicap",
                        "selection": "H",
                        "odds_decimal": float(str(line).replace("+", "")),
                    }
                )
            for key, selection in (("h", "让胜"), ("d", "让平"), ("a", "让负")):
                append_odd(rows, match, captured_at, source, "让球胜平负", selection, item.get(key))
        elif pool_code == "TTG":
            for key, selection in [(f"s{i}", str(i)) for i in range(7)] + [("s7", "7+")]:
                append_odd(rows, match, captured_at, source, "总进球", selection, item.get(key))

    return rows


def append_odd(
    rows: list[dict[str, Any]],
    match: dict[str, Any],
    captured_at: str,
    source: str,
    market: str,
    selection: str,
    value: Any,
) -> None:
    try:
        odds = float(str(value).strip())
    except (TypeError, ValueError):
        return
    if odds <= 1:
        return
    rows.append(
        {
            "match_id": match["match_id"],
            "captured_at": captured_at,
            "source": source,
            "bookmaker": "中国体育彩票",
            "market": market,
            "selection": selection,
            "odds_decimal": odds,
        }
    )


def build_serverless_state(selected_matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    matches = selected_matches or load_matches()
    public_fixtures, public_meta = fetch_public_schedule()
    sporttery_fixtures, sporttery_meta = fetch_sporttery_fixtures()
    try:
        aicai_context = fetch_aicai_worldcup_context(matches)
    except Exception as exc:
        aicai_context = {"source": "https://live.aicai.com/league/index.htm?leagueId=1999&tab=4", "fixtures": [], "match_contexts": {}, "count": 0, "error": str(exc)}
    fixtures = merge_fixtures(public_fixtures, [*sporttery_fixtures, *aicai_context.get("fixtures", [])])
    fixture_groups = split_fixtures(fixtures)
    details = []
    errors = []
    for match in matches:
        try:
            history = sporttery_history(match, sporttery_fixtures)
            history.extend(snapshots_for_match(match, aicai_context.get("match_contexts", {}).get(match["match_id"])))
            prediction = build_prediction(match, history)
        except Exception as exc:
            history = []
            prediction = build_prediction(match, history)
            errors.append({"match_id": match.get("match_id"), "error": str(exc)})
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
                "latest_snapshot": history[-1]["captured_at"] if history else None,
                "prediction": prediction,
                "odds_history": history,
            }
        )
    refresh_status = load_json(
        REFRESH_STATUS_PATH,
        {
            "enabled": False,
            "interval_seconds": 14400,
            "running": False,
            "last_started_at": None,
            "last_finished_at": None,
            "last_ok": None,
            "last_error": None,
            "runs": 0,
            "last_summary": {},
        },
    )
    prediction_snapshots = load_json(SERVERLESS_PREDICTION_SNAPSHOTS_PATH, [])
    return {
        "matches": details,
        "sporttery_combos": [],
        "sources": load_sources(),
        "source_health": {},
        "fixtures": {
            "scheduled": [{key: value for key, value in fixture.items() if key != "raw_json"} for fixture in fixture_groups["scheduled"]],
            "finished": [{key: value for key, value in fixture.items() if key != "raw_json"} for fixture in fixture_groups["finished"]],
        },
        "standings": load_standings(),
        "prediction_snapshots": prediction_snapshots,
        "backtests": [],
        "backtest_summary": {
            "count": 0,
            "top1_accuracy": None,
            "top2_accuracy": None,
            "score_accuracy": None,
            "avg_brier": None,
            "avg_log_loss": None,
            "avg_roi": None,
            "by_scenario": [],
            "calibration_buckets": [],
            "tuning_suggestions": ["Vercel 云端为只读模式；赛前归档和赛后回测请在本地运行。"],
        },
        "deployment": {
                "mode": "vercel_readonly",
                "public_schedule_meta": public_meta,
                "sporttery_meta": sporttery_meta,
                "aicai_meta": {
                    "source": aicai_context.get("source"),
                    "count": aicai_context.get("count", 0),
                    "error": aicai_context.get("error"),
                },
                "errors": errors,
            },
        "refresh_status": refresh_status,
    }


def refresh_status_response() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "vercel_git_snapshot",
        "refresh_status": load_json(
            REFRESH_STATUS_PATH,
            {
                "enabled": False,
                "interval_seconds": 14400,
                "running": False,
                "last_started_at": None,
                "last_finished_at": None,
                "last_ok": None,
                "last_error": None,
                "runs": 0,
                "last_summary": {},
            },
        ),
    }


def merge_fixtures(primary: list[dict[str, Any]], secondary: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for fixture in [*primary, *secondary]:
        key = fixture_key(fixture)
        if key in merged:
            merged[key].update({k: v for k, v in fixture.items() if v not in (None, "", [])})
        else:
            merged[key] = dict(fixture)
    return sorted(merged.values(), key=lambda row: row.get("kickoff") or "")


def fixture_key(fixture: dict[str, Any]) -> str:
    return "|".join(
        str(fixture.get(key) or "").strip().lower()
        for key in ("home_team", "away_team", "kickoff")
    )


def fixture_lookup_key(fixture: dict[str, Any]) -> str:
    kickoff = str(fixture.get("kickoff") or "")
    date = kickoff[:10] if kickoff else ""
    return "|".join(
        str(fixture.get(key) or "").strip().lower().replace(" ", "")
        for key in ("home_team", "away_team")
    ) + f"|{date}"


def find_fixture_for_payload(fixtures: list[dict[str, Any]], payload: dict[str, Any]) -> dict[str, Any] | None:
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


def fixture_quality(fixture: dict[str, Any]) -> int:
    source = str(fixture.get("source") or "")
    if source.startswith("爱彩") or fixture.get("aicai_match_id") or str(fixture.get("match_id") or "").startswith("AICAI_"):
        return 5
    if source.startswith("中国体彩") or fixture.get("selling_pools") or fixture.get("sporttery_match_num"):
        return 4
    if any(option.get("play") == "胜平负" for option in fixture.get("odds_summary", []) or []):
        return 3
    if re.search(r"T(0[1-9]|1\d|2[0-3]):", str(fixture.get("kickoff") or "")):
        return 2
    return 1


def select_fixture_window(fixtures: list[dict[str, Any]], selected_fixture: dict[str, Any] | None, limit: int) -> list[dict[str, Any]]:
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
    selected: list[dict[str, Any]] = [selected_fixture]
    seen = {fixture_lookup_key(selected_fixture)}
    for fixture in candidates:
        if len(selected) >= limit:
            break
        key = fixture_lookup_key(fixture)
        if key in seen:
            continue
        selected.append(fixture)
        seen.add(key)
    return selected


def parse_handicap_from_fixture(fixture: dict[str, Any]) -> int | None:
    for row in fixture.get("odds_summary", []) or []:
        play = str(row.get("play") or "")
        match = re.search(r"让球\(([+-]?\d+(?:\.\d+)?)\)", play)
        if match:
            try:
                return int(float(match.group(1)))
            except ValueError:
                return None
    return None


def parse_total_line_from_fixture(fixture: dict[str, Any]) -> float | None:
    for row in fixture.get("aicai_odds_summary", []) or []:
        play = str(row.get("play") or "")
        match = re.search(r"大小球\((\d+(?:\.\d+)?)\)", play)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
    return None


def parse_h2h_odds_from_fixture(fixture: dict[str, Any]) -> dict[str, float] | None:
    for source_key in ("odds_summary", "aicai_odds_summary"):
        for row in fixture.get(source_key, []) or []:
            play = str(row.get("play") or "")
            if play not in {"胜平负", "爱彩欧赔"}:
                continue
            values: dict[str, float] = {}
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


def implied_probs(odds: dict[str, float] | None) -> dict[str, float] | None:
    if not odds:
        return None
    inv = {key: 1 / value for key, value in odds.items() if value and value > 1}
    total = sum(inv.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in inv.items()}


def expected_goals_from_fixture(fixture: dict[str, Any], odds: dict[str, float] | None) -> dict[str, float]:
    total = parse_total_line_from_fixture(fixture) or 2.4
    probs = implied_probs(odds) or {"home": 0.38, "draw": 0.28, "away": 0.34}
    edge = probs.get("home", 0.38) - probs.get("away", 0.34)
    home_share = max(0.25, min(0.75, 0.5 + edge * 0.55))
    home = max(0.35, total * home_share)
    away = max(0.35, total - home)
    return {"home": round(home, 2), "away": round(away, 2)}


def auto_match_id(fixture: dict[str, Any]) -> str:
    source_id = str(fixture.get("match_id") or "")
    if source_id and source_id.startswith("AICAI_"):
        return source_id
    seed = fixture_lookup_key(fixture) or fixture_key(fixture) or source_id
    return "AUTO_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10].upper()


def match_from_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
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


def select_matches_response(payload: dict[str, Any]) -> dict[str, Any]:
    base_matches = load_matches()
    public_fixtures, _public_meta = fetch_public_schedule()
    sporttery_fixtures, _sporttery_meta = fetch_sporttery_fixtures()
    try:
        aicai_context = fetch_aicai_worldcup_context(base_matches)
    except Exception:
        aicai_context = {"fixtures": []}
    fixtures = merge_fixtures(public_fixtures, [*sporttery_fixtures, *aicai_context.get("fixtures", [])])
    selected_fixture = find_fixture_for_payload(fixtures, payload)
    selected = select_fixture_window(fixtures, selected_fixture, limit=4 if payload.get("mode") == "next4" else 1)
    if not selected:
        return {"ok": False, "error": "未找到可加入预测的赛程，请先刷新赛程。", "state": build_serverless_state()}
    matches = [match_from_fixture(fixture) for fixture in selected]
    return {
        "ok": True,
        "selected": [match["match_id"] for match in matches],
        "message": "已加入预测并刷新",
        "state": build_serverless_state(matches),
    }


def write_json(handler: BaseHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class JsonHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        write_json(self, build_serverless_state())

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}
        if self.path.startswith("/api/matches/select"):
            result = select_matches_response(payload)
            write_json(self, result, status=200 if result.get("ok") else 404)
            return
        write_json(
            self,
            {
                "ok": True,
                "mode": "vercel_readonly",
                "message": "Vercel 云端为只读模式，已重新生成当前预测状态。",
                "state": build_serverless_state(),
            },
        )
