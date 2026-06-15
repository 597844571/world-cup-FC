from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any


USER_AGENT = "Mozilla/5.0 (compatible; WorldCupPredictionTerminal/1.0; public-data-monitor)"
SPORTTERY_REFERER = "https://m.sporttery.cn/mjc/jsq/zqspf/"
SPORTTERY_API = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchCalculatorV1.qry"
SPORTTERY_MATCH_LIST_API = "https://webapi.sporttery.cn/gateway/uniform/football/getMatchListV1.qry?clientCode=3001"


class PublicSourceError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_text(url: str, timeout: int = 18, headers: dict[str, str] | None = None) -> str:
    if not url:
        raise PublicSourceError("source url is empty")
    request_headers = {"User-Agent": USER_AGENT}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in {403, 451} or "WAF" in body or "拦截" in body:
            raise PublicSourceError(f"official/public endpoint blocked by WAF or access policy: HTTP {exc.code}") from exc
        raise
    with response:
        return response.read().decode("utf-8", errors="replace")


def parse_decimal(value: Any) -> float:
    if value is None:
        raise PublicSourceError("missing odds value")
    text = str(value).strip().replace(",", ".")
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        raise PublicSourceError(f"cannot parse decimal odds from {value!r}")
    odd = float(match.group(0))
    if odd <= 1:
        raise PublicSourceError(f"invalid decimal odds {odd}")
    return odd


def dig(payload: Any, path: str) -> Any:
    current = payload
    for part in path.split("."):
        part = part.strip()
        if not part:
            continue
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise PublicSourceError(f"path {path!r} cannot continue at {part!r}")
    return current


def scrape_public_json(source: dict[str, Any], match: dict[str, Any]) -> list[dict[str, Any]]:
    text = fetch_text(source["url"])
    payload = json.loads(text)
    paths = source.get("paths", {})
    rows = []
    for selection in ("home", "draw", "away"):
        path = paths.get(selection)
        if not path:
            raise PublicSourceError(f"missing json path for {selection}")
        rows.append(row(source, selection, parse_decimal(dig(payload, path))))
    return rows


def scrape_public_html_regex(source: dict[str, Any], match: dict[str, Any]) -> list[dict[str, Any]]:
    html = fetch_text(source["url"])
    patterns = source.get("patterns", {})
    rows = []
    for selection in ("home", "draw", "away"):
        pattern = patterns.get(selection)
        if not pattern:
            raise PublicSourceError(f"missing html regex for {selection}")
        match_obj = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if not match_obj:
            raise PublicSourceError(f"regex did not match {selection}")
        value = match_obj.group(1) if match_obj.groups() else match_obj.group(0)
        rows.append(row(source, selection, parse_decimal(value)))
    return rows


def parse_process_number(value: Any) -> float:
    text = str(value or "").strip().replace("%", "").replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        raise PublicSourceError(f"cannot parse process number from {value!r}")
    return float(match.group(0))


def scrape_match_process_html_regex(source: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    html = fetch_text(
        source["url"],
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": source.get("accept_language", "zh-CN,zh;q=0.9,en;q=0.7"),
        },
    )
    page_text = re.sub(r"\s+", " ", html)
    home_names = names_for(match, "home")
    away_names = names_for(match, "away")
    normalized_page = normalize_name(page_text)
    if home_names and away_names and not (
        any(name and name in normalized_page for name in home_names)
        and any(name and name in normalized_page for name in away_names)
    ):
        raise PublicSourceError("process page did not expose both configured teams in static HTML")

    patterns = source.get("patterns", {})
    if not patterns:
        raise PublicSourceError("process source has no regex patterns; configure static HTML or discovered JSON endpoint first")

    metric_map = {
        "shots": ("home_shots", "away_shots"),
        "shots_on_target": ("home_shots_on_target", "away_shots_on_target"),
        "possession": ("home_possession", "away_possession"),
        "fouls": ("home_fouls", "away_fouls"),
        "yellow_cards": ("home_yellow_cards", "away_yellow_cards"),
        "red_cards": ("home_red_cards", "away_red_cards"),
        "goals": ("home_goals", "away_goals"),
    }
    stats = {"home": {}, "away": {}}
    matched = 0
    for metric, (home_key, away_key) in metric_map.items():
        for side, key in (("home", home_key), ("away", away_key)):
            pattern = patterns.get(key)
            if not pattern:
                continue
            match_obj = re.search(pattern, page_text, flags=re.IGNORECASE | re.DOTALL)
            if not match_obj:
                continue
            value = match_obj.group(1) if match_obj.groups() else match_obj.group(0)
            stats[side][metric] = parse_process_number(value)
            matched += 1
    if matched < int(source.get("min_metrics", 3)):
        raise PublicSourceError(f"process regex matched too few metrics: {matched}")
    return {
        "source": source["source_id"],
        "captured_at": utc_now(),
        "stats": stats,
        "notes": source.get("notes", ""),
    }


def scrape_msn_match_process(source: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    try:
        return scrape_match_process_html_regex(source, match)
    except PublicSourceError as exc:
        if "no regex patterns" not in str(exc):
            raise
        html = fetch_text(
            source["url"],
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": source.get("accept_language", "zh-CN,zh;q=0.9,en;q=0.7"),
            },
        )
        normalized_page = normalize_name(html)
        home_seen = any(name and name in normalized_page for name in names_for(match, "home"))
        away_seen = any(name and name in normalized_page for name in names_for(match, "away"))
        if home_seen and away_seen:
            raise PublicSourceError("MSN page exposes teams but no stable stat patterns/API mapping is configured")
        raise PublicSourceError("MSN static HTML does not expose this match; use discovered MSN JSON endpoint or manual process stats")


def scrape_match_process_source(source: dict[str, Any], match: dict[str, Any]) -> dict[str, Any]:
    source_type = source.get("type")
    if source_type == "msn_match_process":
        return scrape_msn_match_process(source, match)
    if source_type == "match_process_html_regex":
        return scrape_match_process_html_regex(source, match)
    raise PublicSourceError(f"unsupported process source type {source_type}")


def row(source: dict[str, Any], selection: str, odds_decimal: float) -> dict[str, Any]:
    return {
        "source": source["source_id"],
        "bookmaker": source.get("bookmaker", source.get("name", source["source_id"])),
        "market": "h2h",
        "selection": selection,
        "odds_decimal": odds_decimal,
    }


def sporttery_url(source: dict[str, Any]) -> str:
    pools = source.get("pool_codes", ["had", "hhad", "crs", "ttg", "hafu"])
    channel = source.get("channel", "m")
    return f"{SPORTTERY_API}?channel={channel}&poolCode={','.join(pools)}"


def normalize_name(value: str) -> str:
    return re.sub(r"[\s　]+", "", value or "").lower()


def names_for(match: dict[str, Any], side: str) -> set[str]:
    key = "home" if side == "home" else "away"
    names = {match[f"{key}_team"], *match.get(f"{key}_aliases", [])}
    return {normalize_name(name) for name in names if name}


def match_sporttery_fixture(match: dict[str, Any], fixture: dict[str, Any]) -> bool:
    home_names = names_for(match, "home")
    away_names = names_for(match, "away")
    fixture_home = normalize_name(fixture.get("homeTeamAllName") or fixture.get("homeTeamAbbName") or "")
    fixture_away = normalize_name(fixture.get("awayTeamAllName") or fixture.get("awayTeamAbbName") or "")
    if fixture_home in home_names and fixture_away in away_names:
        return True
    fixture_text = normalize_name(
        " ".join(
            str(fixture.get(key, ""))
            for key in ("homeTeamAllName", "homeTeamAbbName", "homeTeamAbbEnName", "awayTeamAllName", "awayTeamAbbName", "awayTeamAbbEnName")
        )
    )
    return any(name and name in fixture_text for name in home_names) and any(name and name in fixture_text for name in away_names)


def sporttery_row(source: dict[str, Any], market: str, selection: str, value: Any, match_id: str | None = None) -> dict[str, Any] | None:
    try:
        odds = parse_decimal(value)
    except PublicSourceError:
        return None
    row_data = {
        "source": source["source_id"],
        "bookmaker": source.get("bookmaker", source.get("name", source["source_id"])),
        "market": market,
        "selection": selection,
        "odds_decimal": odds,
    }
    if match_id:
        row_data["external_match_id"] = match_id
    return row_data


def scrape_sporttery_official(source: dict[str, Any], match: dict[str, Any]) -> list[dict[str, Any]]:
    text = fetch_text(
        source.get("url") or sporttery_url(source),
        headers={
            "Referer": source.get("referer", SPORTTERY_REFERER),
            "Accept": "application/json,text/plain,*/*",
        },
    )
    payload = json.loads(text)
    if payload.get("errorCode") not in {0, "0", None}:
        raise PublicSourceError(f"sporttery api errorCode={payload.get('errorCode')}")
    value = payload.get("value") or {}
    rows: list[dict[str, Any]] = []
    for group in value.get("matchInfoList", []):
        for fixture in group.get("subMatchList", []):
            if not match_sporttery_fixture(match, fixture):
                continue
            external_id = str(fixture.get("matchId", ""))
            had = fixture.get("had") or {}
            for key, selection, model_selection in (("h", "胜", "home"), ("d", "平", "draw"), ("a", "负", "away")):
                item = sporttery_row(source, "胜平负", selection, had.get(key), external_id)
                proxy = sporttery_row(source, "h2h", model_selection, had.get(key), external_id)
                if item:
                    rows.append(item)
                if proxy:
                    rows.append(proxy)

            hhad = fixture.get("hhad") or {}
            if hhad.get("goalLine") not in {None, ""}:
                rows.append(
                    {
                        "source": source["source_id"],
                        "bookmaker": source.get("bookmaker", source.get("name", source["source_id"])),
                        "market": "sporttery_handicap",
                        "selection": "H",
                        "odds_decimal": float(str(hhad.get("goalLine")).replace("+", "")),
                        "external_match_id": external_id,
                    }
                )
            for key, selection in (("h", "让胜"), ("d", "让平"), ("a", "让负")):
                item = sporttery_row(source, "让球胜平负", selection, hhad.get(key), external_id)
                if item:
                    rows.append(item)
            ttg = fixture.get("ttg") or {}
            for key, selection in [(f"s{i}", str(i)) for i in range(7)] + [("s7", "7+")]:
                item = sporttery_row(source, "总进球", selection, ttg.get(key), external_id)
                if item:
                    rows.append(item)

            crs = fixture.get("crs") or {}
            score_keys = {
                "1:0": "s01s00", "2:0": "s02s00", "2:1": "s02s01", "3:0": "s03s00", "3:1": "s03s01", "3:2": "s03s02",
                "4:0": "s04s00", "4:1": "s04s01", "4:2": "s04s02", "5:0": "s05s00", "5:1": "s05s01", "5:2": "s05s02",
                "胜其它": "s1sh", "0:0": "s00s00", "1:1": "s01s01", "2:2": "s02s02", "3:3": "s03s03", "平其它": "s1sd",
                "0:1": "s00s01", "0:2": "s00s02", "1:2": "s01s02", "0:3": "s00s03", "1:3": "s01s03", "2:3": "s02s03",
                "0:4": "s00s04", "1:4": "s01s04", "2:4": "s02s04", "0:5": "s00s05", "1:5": "s01s05", "2:5": "s02s05", "负其它": "s1sa",
            }
            for selection, key in score_keys.items():
                item = sporttery_row(source, "比分", selection, crs.get(key), external_id)
                if item:
                    rows.append(item)

            hafu = fixture.get("hafu") or {}
            hafu_keys = {
                "胜胜": "hh", "胜平": "hd", "胜负": "ha",
                "平胜": "dh", "平平": "dd", "平负": "da",
                "负胜": "ah", "负平": "ad", "负负": "aa",
            }
            for selection, key in hafu_keys.items():
                item = sporttery_row(source, "半全场", selection, hafu.get(key), external_id)
                if item:
                    rows.append(item)
            if rows:
                return rows
    raise PublicSourceError("sporttery fixture not found for configured teams")


def sporttery_pool_meta_rows(source: dict[str, Any], fixture: dict[str, Any], external_id: str) -> list[dict[str, Any]]:
    rows = []
    for pool in fixture.get("poolList", []) or []:
        pool_code = str(pool.get("poolCode", "")).upper()
        if not pool_code:
            continue
        base = {
            "source": source["source_id"],
            "bookmaker": source.get("bookmaker", source.get("name", source["source_id"])),
            "selection": pool_code,
            "external_match_id": external_id,
        }
        for market, key in (
            ("sporttery_pool_open", "cbtValue"),
            ("sporttery_pool_single", "cbtSingle"),
            ("sporttery_pool_allup", "cbtAllUp"),
        ):
            try:
                value = float(pool.get(key, 0) or 0)
            except (TypeError, ValueError):
                value = 0.0
            rows.append({**base, "market": market, "odds_decimal": max(value, 0.0)})
    return rows


def scrape_sporttery_match_list(source: dict[str, Any], match: dict[str, Any]) -> list[dict[str, Any]]:
    text = fetch_text(
        source.get("url") or SPORTTERY_MATCH_LIST_API,
        headers={
            "Referer": source.get("referer", "https://www.lottery.gov.cn/jc/zqszsc/"),
            "Accept": "application/json,text/plain,*/*",
        },
    )
    payload = json.loads(text)
    if payload.get("errorCode") not in {0, "0", None}:
        raise PublicSourceError(f"sporttery match list api errorCode={payload.get('errorCode')}")
    value = payload.get("value") or {}
    for group in value.get("matchInfoList", []):
        for fixture in group.get("subMatchList", []):
            if not match_sporttery_fixture(match, fixture):
                continue
            external_id = str(fixture.get("matchId", ""))
            rows: list[dict[str, Any]] = []
            rows.extend(sporttery_pool_meta_rows(source, fixture, external_id))
            for item in fixture.get("oddsList", []) or []:
                pool_code = str(item.get("poolCode", "")).upper()
                if pool_code == "HAD":
                    for key, selection, model_selection in (("h", "胜", "home"), ("d", "平", "draw"), ("a", "负", "away")):
                        bet = sporttery_row(source, "胜平负", selection, item.get(key), external_id)
                        proxy = sporttery_row(source, "h2h", model_selection, item.get(key), external_id)
                        if bet:
                            rows.append(bet)
                        if proxy:
                            rows.append(proxy)
                elif pool_code == "HHAD":
                    if item.get("goalLine") not in {None, ""}:
                        rows.append(
                            {
                                "source": source["source_id"],
                                "bookmaker": source.get("bookmaker", source.get("name", source["source_id"])),
                                "market": "sporttery_handicap",
                                "selection": "H",
                                "odds_decimal": float(str(item.get("goalLine")).replace("+", "")),
                                "external_match_id": external_id,
                            }
                        )
                    for key, selection in (("h", "让胜"), ("d", "让平"), ("a", "让负")):
                        bet = sporttery_row(source, "让球胜平负", selection, item.get(key), external_id)
                        if bet:
                            rows.append(bet)
                elif pool_code == "TTG":
                    for key, selection in [(f"s{i}", str(i)) for i in range(7)] + [("s7", "7+")]:
                        bet = sporttery_row(source, "总进球", selection, item.get(key), external_id)
                        if bet:
                            rows.append(bet)
            rows.append(
                {
                    "source": source["source_id"],
                    "bookmaker": source.get("bookmaker", source.get("name", source["source_id"])),
                    "market": "sporttery_match_number",
                    "selection": str(fixture.get("matchNumStr") or fixture.get("matchNum") or external_id),
                    "odds_decimal": 1.0,
                    "external_match_id": external_id,
                }
            )
            return rows
    raise PublicSourceError("sporttery match list fixture not found for configured teams")


def scrape_source(source: dict[str, Any], match: dict[str, Any]) -> list[dict[str, Any]]:
    source_type = source.get("type")
    if source_type == "sporttery_official_calculator":
        return scrape_sporttery_official(source, match)
    if source_type == "sporttery_official_match_list":
        return scrape_sporttery_match_list(source, match)
    if source_type == "public_json_path":
        return scrape_public_json(source, match)
    if source_type == "public_html_regex":
        return scrape_public_html_regex(source, match)
    raise PublicSourceError(f"unsupported public source type {source_type}")


def update_health(
    health: dict[str, Any],
    source: dict[str, Any],
    ok: bool,
    rows: int = 0,
    error: str | None = None,
) -> None:
    source_id = source["source_id"]
    item = health.get(
        source_id,
        {
            "source_id": source_id,
            "success_count": 0,
            "failure_count": 0,
            "last_success_at": None,
            "last_failure_at": None,
            "last_error": None,
            "last_rows": 0,
        },
    )
    if ok:
        item["success_count"] += 1
        item["last_success_at"] = utc_now()
        item["last_error"] = None
        item["last_rows"] = rows
    else:
        item["failure_count"] += 1
        item["last_failure_at"] = utc_now()
        item["last_error"] = error or "unknown error"
        item["last_rows"] = 0
    health[source_id] = item
    time.sleep(float(source.get("polite_delay_seconds", 0)))
