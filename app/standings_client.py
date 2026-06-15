from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .config import STANDINGS_PATH, load_json, save_json
from .scrapers.public_sources import PublicSourceError, update_health
from .source_registry import load_source_health, load_sources, save_source_health


DEFAULT_BING_STANDINGS_URL = (
    "https://cn.bing.com/sportsdetails?"
    + urllib.parse.urlencode(
        {
            "q": "世界杯报道 统计信息",
            "sport": "Soccer",
            "scenario": "League",
            "TimezoneId": "China Standard Time",
            "IANATimezoneId": "Asia/Shanghai",
            "ISOTimezoneKey": "CST",
            "league": "Soccer_InternationalWorldCup",
            "intent": "Standings",
            "seasonyear": "2026",
            "segment": "sports",
            "isl2": "true",
            "form": "ARENL1",
        }
    )
)


TEAM_ALIAS_ZH = {
    "Brazil": "巴西",
    "Brasil": "巴西",
    "Morocco": "摩洛哥",
    "Maroc": "摩洛哥",
    "Qatar": "卡塔尔",
    "Switzerland": "瑞士",
    "Swiss": "瑞士",
    "Australia": "澳大利亚",
    "Socceroos": "澳大利亚",
    "Türkiye": "土耳其",
    "Turkey": "土耳其",
    "Turkiye": "土耳其",
    "Haiti": "海地",
    "Scotland": "苏格兰",
    "Mexico": "墨西哥",
    "South Korea": "韩国",
    "Korea": "韩国",
    "Czech Republic": "捷克",
    "Czech": "捷克",
    "South Africa": "南非",
    "Canada": "加拿大",
    "Bosnia": "波斯尼亚",
    "Bosnia and Herzegovina": "波斯尼亚",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_text(url: str, timeout: int = 18) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WorldCupPredictionTerminal/1.0; standings-monitor)",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def parse_bing_standings(html_text: str, source_id: str = "bing_worldcup_standings") -> dict[str, Any]:
    tables = re.findall(r"<table>(.*?)</table>", html_text, flags=re.IGNORECASE | re.DOTALL)
    groups: list[dict[str, Any]] = []
    for table in tables:
        header = re.search(r'class="bsp_td_fixed"[^>]*title="([^"]+)"', table, flags=re.IGNORECASE)
        if not header:
            continue
        group_name = html.unescape(header.group(1)).strip()
        rows = []
        for raw_row in re.findall(r'<tr class="bsp_row_item.*?</tr>', table, flags=re.IGNORECASE | re.DOTALL):
            team_match = re.search(r'class="bsp_row_teamname"[^>]*title="([^"]+)"', raw_row, flags=re.IGNORECASE)
            if not team_match:
                continue
            values = re.findall(r'<div class="colVal(?:\s+bsp_col_pts)?">(-?\d+)</div>', raw_row, flags=re.IGNORECASE)
            if len(values) < 8:
                continue
            rank_match = re.search(r'class="bsp_row_rank">(\d+)</span>', raw_row, flags=re.IGNORECASE)
            form = []
            if "bsp_won_icon" in raw_row:
                form.append("W")
            if "bsp_draw_icon" in raw_row:
                form.append("D")
            if "bsp_loss_icon" in raw_row:
                form.append("L")
            rows.append(
                {
                    "rank": int(rank_match.group(1)) if rank_match else len(rows) + 1,
                    "team": html.unescape(team_match.group(1)).strip(),
                    "played": int(values[0]),
                    "wins": int(values[1]),
                    "draws": int(values[2]),
                    "losses": int(values[3]),
                    "goals_for": int(values[4]),
                    "goals_against": int(values[5]),
                    "goal_diff": int(values[6]),
                    "points": int(values[7]),
                    "recent_form": form,
                }
            )
        if rows:
            groups.append({"group": group_name, "teams": rows})
    if not groups:
        raise PublicSourceError("Bing standings table not found")
    return {
        "source": source_id,
        "captured_at": utc_now(),
        "competition": "FIFA World Cup 2026",
        "groups": groups,
    }


def fetch_bing_standings() -> tuple[dict[str, Any] | None, dict[str, Any]]:
    sources = [item for item in load_sources() if item.get("enabled") and item.get("type") == "bing_worldcup_standings"]
    source = sources[0] if sources else {
        "source_id": "bing_worldcup_standings",
        "url": DEFAULT_BING_STANDINGS_URL,
        "polite_delay_seconds": 0,
    }
    health = load_source_health()
    try:
        payload = parse_bing_standings(fetch_text(source.get("url") or DEFAULT_BING_STANDINGS_URL), source["source_id"])
    except Exception as exc:
        update_health(health, source, ok=False, error=str(exc))
        save_source_health(health)
        return None, {"source": source["source_id"], "count": 0, "error": str(exc)}
    save_json(STANDINGS_PATH, payload)
    update_health(health, source, ok=True, rows=sum(len(group["teams"]) for group in payload["groups"]))
    save_source_health(health)
    return payload, {"source": source["source_id"], "count": len(payload["groups"]), "error": None}


def load_standings() -> dict[str, Any]:
    return load_json(STANDINGS_PATH, {"source": None, "captured_at": None, "groups": []})


def normalize_team_name(value: str) -> str:
    return re.sub(r"[\s　]+", "", value or "").lower()


def team_name_candidates(match: dict[str, Any], side: str) -> set[str]:
    prefix = "home" if side == "home" else "away"
    raw_names = {match.get(f"{prefix}_team", ""), *match.get(f"{prefix}_aliases", [])}
    expanded = set(raw_names)
    for name in list(raw_names):
        translated = TEAM_ALIAS_ZH.get(str(name))
        if translated:
            expanded.add(translated)
    return {normalize_team_name(str(name)) for name in expanded if name}


def find_group_context(match: dict[str, Any], standings: dict[str, Any] | None = None) -> dict[str, Any] | None:
    standings = standings or load_standings()
    home_names = team_name_candidates(match, "home")
    away_names = team_name_candidates(match, "away")
    for group in standings.get("groups", []):
        teams = group.get("teams", [])
        home_row = next((team for team in teams if normalize_team_name(team.get("team", "")) in home_names), None)
        away_row = next((team for team in teams if normalize_team_name(team.get("team", "")) in away_names), None)
        if home_row or away_row:
            return {
                "source": standings.get("source"),
                "captured_at": standings.get("captured_at"),
                "group": group.get("group"),
                "home": home_row,
                "away": away_row,
                "teams": teams,
            }
    return None
