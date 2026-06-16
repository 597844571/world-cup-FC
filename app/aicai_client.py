from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any


AICAI_SPORTDATA_URL = "https://sport.ttyingqiu.com/sportdata/f"
AICAI_REFERER = "https://live.aicai.com/league/index.htm?leagueId=1999&tab=4"
AICAI_WORLD_CUP_LEAGUE_ID = 1999
AICAI_PROVIDER_ID = 5


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(value: str) -> str:
    return re.sub(r"[\s　]+", "", value or "").lower()


def post_sportdata(payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        AICAI_SPORTDATA_URL,
        data=body,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WorldCupPredictionTerminal/1.0)",
            "Origin": "https://live.aicai.com",
            "Referer": AICAI_REFERER,
            "Content-Type": "application/json",
            "Accept": "application/json,text/plain,*/*",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
    data = json.loads(raw)
    if str(data.get("code")) != "1":
        raise ValueError(data.get("msg") or f"Aicai api failed: {payload.get('apiName')}")
    return data


def fetch_worldcup_season() -> dict[str, Any]:
    data = post_sportdata({"apiName": "queryLeagueSeasons", "leagueId": AICAI_WORLD_CUP_LEAGUE_ID})
    seasons = data.get("leagueInfoSimpleVo", {}).get("leagueSeasons", []) or []
    season = next((item for item in seasons if str(item.get("name")) == "2026"), seasons[0] if seasons else {})
    return {
        "league_id": AICAI_WORLD_CUP_LEAGUE_ID,
        "season_id": int(season.get("id") or 40531),
        "season_flag": int(season.get("seasonFlag") or 0),
        "season_name": str(season.get("name") or "2026"),
    }


def fetch_match_list(season: dict[str, Any]) -> list[dict[str, Any]]:
    payload = {
        "apiName": "getLeagueMatchList",
        "leagueId": season["league_id"],
        "seasonId": season["season_id"],
        "seasonFlag": season["season_flag"],
        "seasonName": season["season_name"],
        "pageNo": 1,
        "pageSize": 1000,
    }
    data = post_sportdata(payload)
    return data.get("matchList") or data.get("list") or []


def fetch_league_stats(season: dict[str, Any]) -> dict[str, Any]:
    stats: dict[str, Any] = {"season": season}
    calls = {
        "league_result": {
            "apiName": "queryLeagueStatistics",
            "leagueId": season["league_id"],
            "rateType": 0,
            "seasonFlag": season["season_flag"],
            "seasonId": season["season_id"],
            "seasonName": season["season_name"],
        },
        "half_full": {
            "apiName": "getLeagueHalfAllStatApi",
            "dataType": 0,
            "leagueId": season["league_id"],
            "seasonFlag": season["season_flag"],
            "seasonName": season["season_name"],
        },
        "total_goals": {
            "apiName": "getLeaguePointsStatApi",
            "dataType": 0,
            "leagueId": season["league_id"],
            "seasonFlag": season["season_flag"],
            "seasonName": season["season_name"],
        },
        "scorelines": {
            "apiName": "getLeagueTeamGeneralScoreAicai",
            "type": 0,
            "leagueId": season["league_id"],
            "seasonId": season["season_id"],
        },
    }
    for key, payload in calls.items():
        try:
            stats[key] = post_sportdata(payload)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            stats[key] = {"error": str(exc)}
    return stats


def fetch_market_details(match_ids: list[int], provider_id: int = AICAI_PROVIDER_ID) -> dict[int, dict[str, Any]]:
    if not match_ids:
        return {}
    output: dict[int, dict[str, Any]] = {int(match_id): {} for match_id in match_ids}
    calls = [
        ("europe", "getListMatchEuropeOdds"),
        ("asia", "getListMatchAsiaPrimaryOdds"),
        ("bigsmall", "getListMatchBigSmallOdds"),
    ]
    for key, api_name in calls:
        try:
            data = post_sportdata({"apiName": api_name, "matchIdList": match_ids, "providerId": provider_id})
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            for item in output.values():
                item.setdefault("errors", []).append(f"{key}: {exc}")
            continue
        for row in data.get("list", []) or []:
            match_id = int(row.get("matchId") or 0)
            if match_id:
                output.setdefault(match_id, {})[key] = row
    return output


def aicai_fixture(item: dict[str, Any]) -> dict[str, Any]:
    home_score, away_score = score_values(item.get("score"))
    return {
        "match_id": f"AICAI_{item.get('matchId')}",
        "source": "爱彩世界杯公开数据",
        "competition": item.get("leagueName") or "世界杯",
        "stage": item.get("stageName") or item.get("round") or item.get("groupName"),
        "home_team": item.get("homeName") or "未知球队",
        "away_team": item.get("awayName") or "未知球队",
        "kickoff": aicai_kickoff(item.get("matchDate"), item.get("matchTime")),
        "status": "finished" if home_score is not None and away_score is not None else "scheduled",
        "home_score": home_score,
        "away_score": away_score,
        "venue": item.get("groupName"),
        "aicai_match_id": item.get("matchId"),
        "aicai_rank": {"home": item.get("homeRank"), "away": item.get("awayRank")},
        "aicai_odds_summary": compact_market_summary(item),
        "raw_json": item,
    }


def aicai_kickoff(match_date: Any, match_time: Any) -> str | None:
    if not match_date or not match_time:
        return None
    return f"{match_date}T{match_time}:00+08:00"


def score_values(score: Any) -> tuple[int | None, int | None]:
    if not isinstance(score, list) or len(score) < 2:
        return None, None
    text = str(score[1] or "").strip()
    if ":" not in text:
        return None, None
    left, right = text.split(":", 1)
    try:
        return int(left), int(right)
    except ValueError:
        return None, None


def parse_triplet(value: Any) -> tuple[float | None, str | None, float | None, int | None]:
    parts = str(value or "").split(";")
    if len(parts) < 3:
        return None, None, None, None
    try:
        left = float(parts[0])
    except ValueError:
        left = None
    try:
        right = float(parts[2])
    except ValueError:
        right = None
    try:
        result = int(parts[3]) if len(parts) >= 4 and parts[3] != "" else None
    except ValueError:
        result = None
    return left, parts[1], right, result


def parse_europe(value: Any) -> tuple[float | None, float | None, float | None, int | None]:
    parts = str(value or "").split(";")
    if len(parts) < 3:
        return None, None, None, None
    try:
        result = int(parts[3]) if len(parts) >= 4 and parts[3] != "" else None
    except ValueError:
        result = None
    out: list[float | None] = []
    for part in parts[:3]:
        try:
            out.append(float(part))
        except ValueError:
            out.append(None)
    return out[0], out[1], out[2], result


def compact_market_summary(item: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    home, draw, away, _ = parse_europe(item.get("oddsEurope"))
    if home and draw and away:
        rows.append({"play": "爱彩欧赔", "options": [{"name": "胜", "sp": home}, {"name": "平", "sp": draw}, {"name": "负", "sp": away}]})
    home_water, line, away_water, _ = parse_triplet(item.get("oddsAsia"))
    if line:
        rows.append({"play": f"让球市场参考({line})", "options": [{"name": "主方向", "sp": home_water}, {"name": "客方向", "sp": away_water}]})
    over_water, total_line, under_water, _ = parse_triplet(item.get("bigsmall"))
    if total_line:
        rows.append({"play": f"大小球({total_line})", "options": [{"name": "大", "sp": over_water}, {"name": "小", "sp": under_water}]})
    return rows


def fixture_matches(match: dict[str, Any], fixture: dict[str, Any]) -> bool:
    home_names = {match.get("home_team", ""), *match.get("home_aliases", [])}
    away_names = {match.get("away_team", ""), *match.get("away_aliases", [])}
    return normalize_name(fixture.get("homeName", "")) in {normalize_name(str(x)) for x in home_names if x} and normalize_name(
        fixture.get("awayName", "")
    ) in {normalize_name(str(x)) for x in away_names if x}


def build_match_context(match: dict[str, Any], fixtures: list[dict[str, Any]], market_details: dict[int, dict[str, Any]]) -> dict[str, Any] | None:
    fixture = next((item for item in fixtures if fixture_matches(match, item)), None)
    if not fixture:
        return None
    match_id = int(fixture.get("matchId") or 0)
    details = market_details.get(match_id, {})
    context = {
        "source": "aicai_worldcup_stats",
        "aicai_match_id": match_id,
        "teams": f"{fixture.get('homeName')} vs {fixture.get('awayName')}",
        "kickoff": aicai_kickoff(fixture.get("matchDate"), fixture.get("matchTime")),
        "rank": {"home": fixture.get("homeRank"), "away": fixture.get("awayRank")},
        "score": fixture.get("score"),
        "europe": normalize_europe(fixture, details.get("europe")),
        "asia": normalize_asia(fixture, details.get("asia")),
        "bigsmall": normalize_bigsmall(fixture, details.get("bigsmall")),
    }
    return context


def normalize_europe(fixture: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any] | None:
    current = detail or {}
    if current:
        first = [current.get("firstWinOdds"), current.get("firstDrawOdds"), current.get("firstLoseOdds")]
        latest = [current.get("winOdds"), current.get("drawOdds"), current.get("loseOdds")]
        provider = current.get("providerName") or "爱彩欧赔"
    else:
        home, draw, away, result = parse_europe(fixture.get("oddsEurope"))
        first = [None, None, None]
        latest = [home, draw, away]
        provider = "爱彩欧赔"
        current = {"result": result}
    try:
        latest_nums = [float(x) for x in latest]
    except (TypeError, ValueError):
        return None
    first_nums: list[float | None] = []
    for value in first:
        try:
            first_nums.append(float(value))
        except (TypeError, ValueError):
            first_nums.append(None)
    return {
        "provider": provider,
        "first": {"home": first_nums[0], "draw": first_nums[1], "away": first_nums[2]},
        "latest": {"home": latest_nums[0], "draw": latest_nums[1], "away": latest_nums[2]},
        "movement": {
            "home": movement(first_nums[0], latest_nums[0]),
            "draw": movement(first_nums[1], latest_nums[1]),
            "away": movement(first_nums[2], latest_nums[2]),
        },
    }


def normalize_asia(fixture: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any] | None:
    latest_home, latest_line, latest_away, latest_result = parse_triplet(fixture.get("oddsAsia"))
    first_line = detail.get("firstHandicap") if detail else None
    line = detail.get("handicap") if detail else latest_line
    if not line:
        return None
    return {
        "provider": (detail or {}).get("providerName") or "爱彩让球市场参考",
        "first_line": first_line,
        "latest_line": line,
        "home_water": latest_home,
        "away_water": latest_away,
        "result_code": (detail or {}).get("asiaTapeResult", latest_result),
    }


def normalize_bigsmall(fixture: dict[str, Any], detail: dict[str, Any] | None) -> dict[str, Any] | None:
    over, latest_line, under, result = parse_triplet(fixture.get("bigsmall"))
    first_line = detail.get("firstHandicap") if detail else None
    line = detail.get("handicap") if detail else latest_line
    if not line:
        return None
    return {
        "provider": (detail or {}).get("providerName") or "爱彩大小球",
        "first_line": first_line,
        "latest_line": line,
        "over_water": over,
        "under_water": under,
        "result_code": (detail or {}).get("bigSmallTapeResult", result),
    }


def movement(first: float | None, latest: float | None) -> float | None:
    if first is None or latest is None:
        return None
    return round(latest - first, 4)


def snapshots_for_match(match: dict[str, Any], context: dict[str, Any] | None, captured_at: str | None = None) -> list[dict[str, Any]]:
    if not context or not context.get("europe"):
        return []
    current_ts = captured_at or utc_now()
    opening_ts = "2026-01-01T00:00:00+00:00"
    europe = context["europe"]
    rows: list[dict[str, Any]] = []
    for bucket, ts, source in (("first", opening_ts, "aicai_worldcup_opening"), ("latest", current_ts, "aicai_worldcup_latest")):
        odds = europe.get(bucket) or {}
        for selection in ("home", "draw", "away"):
            value = odds.get(selection)
            if value and float(value) > 1:
                rows.append(
                    {
                        "match_id": match["match_id"],
                        "captured_at": ts,
                        "source": source,
                        "bookmaker": europe.get("provider") or "爱彩欧赔",
                        "market": "h2h",
                        "selection": selection,
                        "odds_decimal": float(value),
                    }
                )
    asia = context.get("asia") or {}
    if asia.get("latest_line"):
        if asia.get("first_line"):
            rows.append(market_row(match, opening_ts, "aicai_worldcup_opening", "爱彩让球市场参考", "aicai_asia_line", "line", asia["first_line"]))
        rows.append(market_row(match, current_ts, "aicai_worldcup_latest", "爱彩让球市场参考", "aicai_asia_line", "line", asia["latest_line"]))
    if asia.get("home_water"):
            rows.append(market_row(match, current_ts, "aicai_worldcup_latest", "爱彩让球市场参考", "aicai_asia_home_water", "home", asia["home_water"]))
    if asia.get("away_water"):
            rows.append(market_row(match, current_ts, "aicai_worldcup_latest", "爱彩让球市场参考", "aicai_asia_away_water", "away", asia["away_water"]))
    bigsmall = context.get("bigsmall") or {}
    if bigsmall.get("latest_line"):
        if bigsmall.get("first_line"):
            rows.append(market_row(match, opening_ts, "aicai_worldcup_opening", "爱彩大小球", "aicai_total_line", "line", bigsmall["first_line"]))
        rows.append(market_row(match, current_ts, "aicai_worldcup_latest", "爱彩大小球", "aicai_total_line", "line", bigsmall["latest_line"]))
    if bigsmall.get("over_water"):
        rows.append(market_row(match, current_ts, "aicai_worldcup_latest", "爱彩大小球", "aicai_total_over_water", "over", bigsmall["over_water"]))
    if bigsmall.get("under_water"):
        rows.append(market_row(match, current_ts, "aicai_worldcup_latest", "爱彩大小球", "aicai_total_under_water", "under", bigsmall["under_water"]))
    return [row for row in rows if row]


def market_row(match: dict[str, Any], captured_at: str, source: str, bookmaker: str, market: str, selection: str, value: Any) -> dict[str, Any] | None:
    numeric = handicap_to_float(value)
    if numeric is None:
        return None
    return {
        "match_id": match["match_id"],
        "captured_at": captured_at,
        "source": source,
        "bookmaker": bookmaker,
        "market": market,
        "selection": selection,
        "odds_decimal": numeric,
    }


def handicap_to_float(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    sign = -1 if text.startswith("-") else 1
    text = text.replace("+", "").replace("-", "")
    parts = text.split("/")
    try:
        nums = [float(part) for part in parts if part != ""]
    except ValueError:
        return None
    if not nums:
        return None
    return sign * sum(nums) / len(nums)


def fetch_aicai_worldcup_context(matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    season = fetch_worldcup_season()
    raw_matches = fetch_match_list(season)
    match_ids = [int(item["matchId"]) for item in raw_matches if item.get("matchId")]
    market_details = fetch_market_details(match_ids)
    fixtures = [aicai_fixture(item) for item in raw_matches]
    stats = fetch_league_stats(season)
    match_contexts = {}
    if matches:
        for match in matches:
            context = build_match_context(match, raw_matches, market_details)
            if context:
                match_contexts[match["match_id"]] = context
    return {
        "source": AICAI_SPORTDATA_URL,
        "season": season,
        "fixtures": fixtures,
        "stats": stats,
        "market_details": market_details,
        "match_contexts": match_contexts,
        "count": len(fixtures),
        "error": None,
    }
