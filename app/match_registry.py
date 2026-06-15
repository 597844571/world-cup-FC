from __future__ import annotations

from typing import Any

from .config import MATCHES_PATH, load_json, save_json
from .odds_store import OddsStore


DEFAULT_MATCHES = [
    {
        "match_id": "BRA_MAR_SAMPLE",
        "home_team": "巴西",
        "away_team": "摩洛哥",
        "home_aliases": ["Brazil", "Brasil"],
        "away_aliases": ["Morocco", "Maroc"],
        "kickoff": "2026-06-13T06:00:00+08:00",
        "stage": "小组赛",
        "neutral": True,
        "home_elo": 2140,
        "away_elo": 1960,
        "manual_odds": {"home": 1.72, "draw": 3.85, "away": 5.2},
        "manual_odds_drift": {"home": -0.01, "draw": 0.01, "away": 0.015},
        "expected_goals": {"home": 1.75, "away": 0.95},
        "lineup_status": "unknown",
        "injury_notes": "未确认最新伤停",
        "tactical_notes": "巴西个人能力和边路爆点占优，摩洛哥具备低位防守和反击路径。",
        "weather_notes": "待确认",
        "referee_notes": "待确认",
        "upset_triggers": {
            "strong_low_block_problem": True,
            "underdog_low_block": True,
            "underdog_counter_speed": True,
            "underdog_set_piece": True,
        },
    },
    {
        "match_id": "QAT_SUI_SAMPLE",
        "home_team": "卡塔尔",
        "away_team": "瑞士",
        "home_aliases": ["Qatar"],
        "away_aliases": ["Switzerland", "Swiss"],
        "kickoff": "2026-06-13T03:00:00+08:00",
        "stage": "小组赛",
        "neutral": True,
        "home_elo": 1700,
        "away_elo": 1905,
        "manual_odds": {"home": 5.6, "draw": 3.95, "away": 1.64},
        "manual_odds_drift": {"home": 0.012, "draw": 0.004, "away": -0.01},
        "expected_goals": {"home": 0.75, "away": 1.65},
        "lineup_status": "unknown",
        "injury_notes": "未确认最新伤停",
        "tactical_notes": "瑞士整体和中轴线更稳定，卡塔尔需要依靠低位防守与转换。",
        "weather_notes": "待确认",
        "referee_notes": "待确认",
        "upset_triggers": {
            "underdog_low_block": True,
            "underdog_set_piece": True,
        },
    },
]


def load_matches() -> list[dict[str, Any]]:
    matches = load_json(MATCHES_PATH, None)
    if matches is None:
        save_json(MATCHES_PATH, DEFAULT_MATCHES)
        matches = DEFAULT_MATCHES
    return matches


def save_matches(matches: list[dict[str, Any]]) -> None:
    save_json(MATCHES_PATH, matches)


def sync_matches(store: OddsStore, matches: list[dict[str, Any]]) -> None:
    for match in matches:
        store.upsert_match(match)


def find_match(matches: list[dict[str, Any]], match_id: str) -> dict[str, Any] | None:
    for match in matches:
        if match["match_id"] == match_id:
            return match
    return None
