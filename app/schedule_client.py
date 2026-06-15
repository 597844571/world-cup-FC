from __future__ import annotations

import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from typing import Any


DEFAULT_SCHEDULE_URLS = [
    "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json",
    "https://raw.githubusercontent.com/openfootball/worldcup.json/master/worldcup/2026/worldcup.json",
]

SPORTTERY_MATCH_LIST_API = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001"


TEAM_ALIASES = {
    "Brazil": "巴西",
    "Morocco": "摩洛哥",
    "Qatar": "卡塔尔",
    "Switzerland": "瑞士",
    "Australia": "澳大利亚",
    "Türkiye": "土耳其",
    "Turkey": "土耳其",
    "Haiti": "海地",
    "Scotland": "苏格兰",
}


def fetch_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "WorldCupPredictionTerminal/1.0 schedule-monitor"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_sporttery_fixtures() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    request = urllib.request.Request(
        SPORTTERY_MATCH_LIST_API,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WorldCupPredictionTerminal/1.0 schedule-monitor)",
            "Referer": "https://www.lottery.gov.cn/jc/zqszsc/",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return [], {"source": SPORTTERY_MATCH_LIST_API, "count": 0, "error": str(exc)}

    fixtures: list[dict[str, Any]] = []
    value = payload.get("value") or {}
    for group in value.get("matchInfoList", []) or []:
        for item in group.get("subMatchList", []) or []:
            pools = [
                str(pool.get("poolCode", "")).upper()
                for pool in item.get("poolList", []) or []
                if pool.get("poolStatus") == "Selling" and str(pool.get("poolCode", "")).strip()
            ]
            if not pools:
                continue
            home = item.get("homeTeamAllName") or item.get("homeTeamAbbName") or "未知球队"
            away = item.get("awayTeamAllName") or item.get("awayTeamAbbName") or "未知球队"
            kickoff = sporttery_kickoff(item.get("matchDate"), item.get("matchTime"))
            match_num = item.get("matchNumStr") or item.get("matchNum") or ""
            fixtures.append(
                {
                    "match_id": f"SPORTTERY_{item.get('matchNumDate') or item.get('businessDate') or ''}_{match_num}",
                    "source": "中国体彩官方竞彩足球",
                    "competition": item.get("leagueAllName") or item.get("matchName") or "世界杯",
                    "stage": match_num,
                    "home_team": home,
                    "away_team": away,
                    "kickoff": kickoff,
                    "status": "scheduled",
                    "home_score": None,
                    "away_score": None,
                    "venue": item.get("remark"),
                    "sporttery_match_num": match_num,
                    "selling_pools": pools,
                    "raw_json": item,
                }
            )
    return fixtures, {"source": SPORTTERY_MATCH_LIST_API, "count": len(fixtures), "error": None}


def sporttery_kickoff(match_date: Any, match_time: Any) -> str | None:
    if not match_date or not match_time:
        return None
    return f"{match_date}T{match_time}:00+08:00"


def fetch_public_schedule(urls: list[str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    errors = []
    for url in urls or DEFAULT_SCHEDULE_URLS:
        try:
            payload = fetch_json(url)
            fixtures = normalize_payload(payload, source=url)
            return fixtures, {"source": url, "count": len(fixtures), "errors": errors}
        except Exception as exc:  # Public sources are best-effort.
            errors.append({"source": url, "error": str(exc)})
    return [], {"source": None, "count": 0, "errors": errors}


def normalize_payload(payload: Any, source: str) -> list[dict[str, Any]]:
    matches = []
    collect_matches(payload, matches)
    return [normalize_match(item, source) for item in matches if looks_like_match(item)]


def collect_matches(node: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(node, list):
        for item in node:
            collect_matches(item, output)
        return
    if not isinstance(node, dict):
        return
    if looks_like_match(node):
        output.append(node)
    for key in ("matches", "games", "fixtures", "rounds", "groups"):
        value = node.get(key)
        if value is not None:
            collect_matches(value, output)


def looks_like_match(item: dict[str, Any]) -> bool:
    keys = set(item)
    has_team_keys = bool({"team1", "team2"} <= keys or {"home_team", "away_team"} <= keys or {"home", "away"} <= keys)
    has_score_or_date = any(key in keys for key in ("date", "datetime", "kickoff", "score", "score1", "home_score"))
    return has_team_keys and has_score_or_date


def normalize_match(item: dict[str, Any], source: str) -> dict[str, Any]:
    home = team_name(item.get("team1") or item.get("home_team") or item.get("home"))
    away = team_name(item.get("team2") or item.get("away_team") or item.get("away"))
    kickoff = item.get("datetime") or item.get("kickoff") or item.get("date")
    home_score, away_score = score_values(item)
    status = "finished" if home_score is not None and away_score is not None else "scheduled"
    match_id = item.get("match_id") or item.get("id") or stable_match_id(home, away, kickoff)
    return {
        "match_id": str(match_id),
        "source": source,
        "competition": item.get("competition") or item.get("name") or "FIFA World Cup",
        "stage": item.get("stage") or item.get("round") or item.get("group"),
        "home_team": home,
        "away_team": away,
        "kickoff": normalize_kickoff(kickoff),
        "status": status,
        "home_score": home_score,
        "away_score": away_score,
        "venue": item.get("stadium") or item.get("venue") or item.get("city"),
    }


def team_name(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("name") or value.get("code") or value.get("key")
    text = str(value or "未知球队")
    return TEAM_ALIASES.get(text, text)


def score_values(item: dict[str, Any]) -> tuple[int | None, int | None]:
    if "score1" in item and "score2" in item:
        return safe_int(item.get("score1")), safe_int(item.get("score2"))
    if "home_score" in item and "away_score" in item:
        return safe_int(item.get("home_score")), safe_int(item.get("away_score"))
    score = item.get("score")
    if isinstance(score, dict):
        return safe_int(score.get("ft1") or score.get("home") or score.get("score1")), safe_int(
            score.get("ft2") or score.get("away") or score.get("score2")
        )
    if isinstance(score, list) and len(score) >= 2:
        return safe_int(score[0]), safe_int(score[1])
    return None, None


def safe_int(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_kickoff(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    if len(text) == 10 and text[4] == "-":
        return f"{text}T00:00:00"
    return text


def stable_match_id(home: str, away: str, kickoff: str | None) -> str:
    seed = f"{home}|{away}|{kickoff or ''}"
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"fixture_{digest}"


def split_fixtures(fixtures: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return {
        "scheduled": [fixture for fixture in fixtures if fixture.get("status") == "scheduled"],
        "finished": [fixture for fixture in fixtures if fixture.get("status") == "finished"],
    }
