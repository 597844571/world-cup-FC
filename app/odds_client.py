from __future__ import annotations

import json
import os
import random
import urllib.parse
import urllib.request
from typing import Any

from .prediction_engine import elo_probabilities
from .scrapers.public_sources import PublicSourceError, scrape_source, update_health
from .source_registry import load_source_health, load_sources, save_source_health


THE_ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/odds"


def manual_snapshots(match: dict[str, Any]) -> list[dict[str, Any]]:
    odds = match.get("manual_odds")
    if not odds:
        base = elo_probabilities(match.get("home_elo", 1800), match.get("away_elo", 1800), match.get("neutral", True))
        margin = 1.07
        odds = {
            "home": round(1 / max(base["home"] / margin, 0.05), 2),
            "draw": round(1 / max(base["draw"] / margin, 0.05), 2),
            "away": round(1 / max(base["away"] / margin, 0.05), 2),
        }
    drift = match.get("manual_odds_drift", {})
    rows = []
    for bookmaker in match.get("bookmakers", ["manual_consensus"]):
        for selection in ("home", "draw", "away"):
            delta = float(drift.get(selection, 0))
            noise = random.uniform(-0.015, 0.015)
            odd = max(1.01, float(odds[selection]) * (1 + delta + noise))
            rows.append(
                {
                    "source": "manual",
                    "bookmaker": bookmaker,
                    "market": "h2h",
                    "selection": selection,
                    "odds_decimal": round(odd, 3),
                }
            )
    return rows


def fetch_the_odds_api(match: dict[str, Any]) -> list[dict[str, Any]]:
    api_key = os.getenv("THE_ODDS_API_KEY")
    if not api_key or not match.get("odds_event_id"):
        return []

    params = urllib.parse.urlencode(
        {
            "apiKey": api_key,
            "regions": os.getenv("ODDS_REGIONS", "eu,uk,us"),
            "markets": "h2h",
            "oddsFormat": "decimal",
        }
    )
    with urllib.request.urlopen(f"{THE_ODDS_API_BASE}?{params}", timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    rows = []
    target_event_id = str(match["odds_event_id"])
    for event in payload:
        if str(event.get("id")) != target_event_id:
            continue
        for bookmaker in event.get("bookmakers", []):
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for outcome in market.get("outcomes", []):
                    selection = resolve_selection(match, outcome.get("name", ""))
                    if selection:
                        rows.append(
                            {
                                "source": "the_odds_api",
                                "bookmaker": bookmaker.get("key", bookmaker.get("title", "unknown")),
                                "market": "h2h",
                                "selection": selection,
                                "odds_decimal": float(outcome["price"]),
                            }
                        )
    return rows


def resolve_selection(match: dict[str, Any], name: str) -> str | None:
    normalized = name.strip().lower()
    if normalized in {"draw", "tie"}:
        return "draw"
    home_names = {match["home_team"].lower(), *(alias.lower() for alias in match.get("home_aliases", []))}
    away_names = {match["away_team"].lower(), *(alias.lower() for alias in match.get("away_aliases", []))}
    if normalized in home_names:
        return "home"
    if normalized in away_names:
        return "away"
    return None


def fetch_odds(match: dict[str, Any]) -> list[dict[str, Any]]:
    rows = fetch_the_odds_api(match)
    if rows:
        return rows

    public_rows = fetch_public_sources(match)
    return public_rows if public_rows else manual_snapshots(match)


def fetch_public_sources(match: dict[str, Any]) -> list[dict[str, Any]]:
    sources = sorted(load_sources(), key=lambda item: item.get("priority", 50))
    health = load_source_health()
    all_rows: list[dict[str, Any]] = []
    odds_source_types = {"sporttery_official_calculator", "sporttery_official_match_list", "public_json_path", "public_html_regex"}
    for source in sources:
        if not source.get("enabled") or source.get("type") not in odds_source_types:
            continue
        try:
            rows = scrape_source(source, match)
        except (PublicSourceError, OSError, ValueError, KeyError, IndexError) as exc:
            update_health(health, source, ok=False, error=str(exc))
            continue
        update_health(health, source, ok=True, rows=len(rows))
        all_rows.extend(rows)
    save_source_health(health)
    return all_rows
