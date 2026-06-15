from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import load_json
from app.match_registry import load_matches
from app.prediction_engine import build_prediction
from app.schedule_client import fetch_sporttery_fixtures
from app.source_registry import load_sources
from app.standings_client import load_standings


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


def build_serverless_state() -> dict[str, Any]:
    matches = load_matches()
    fixtures, sporttery_meta = fetch_sporttery_fixtures()
    details = []
    errors = []
    for match in matches:
        try:
            history = sporttery_history(match, fixtures)
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
    return {
        "matches": details,
        "sporttery_combos": [],
        "sources": load_sources(),
        "source_health": {},
        "fixtures": {
            "scheduled": [
                {
                    key: value
                    for key, value in fixture.items()
                    if key != "raw_json"
                }
                for fixture in fixtures
            ],
            "finished": [],
        },
        "standings": load_standings(),
        "prediction_snapshots": [],
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
            "sporttery_meta": sporttery_meta,
            "errors": errors,
        },
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
        write_json(
            self,
            {
                "ok": True,
                "mode": "vercel_readonly",
                "message": "Vercel 云端为只读模式，已重新生成当前预测状态。",
                "state": build_serverless_state(),
            },
        )

