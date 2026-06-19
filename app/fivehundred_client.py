from __future__ import annotations

import re
import urllib.request
from datetime import datetime, timezone
from html import unescape
from typing import Any


JZQ_URL = "https://trade.500.com/jczq/"

SELECTION_MAP = {"3": "胜", "1": "平", "0": "负"}
TYPE_MARKET_MAP = {"nspf": "胜平负", "spf": "让球胜平负"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(value: str) -> str:
    return re.sub(r"[\s\u3000]+", "", value or "").lower()


def fetch_500_jczq(url: str = JZQ_URL) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; WorldCupPredictionTerminal/1.0; +https://trade.500.com/jczq/)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://trade.500.com/",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read()
    except Exception as exc:
        return [], {"source": url, "count": 0, "error": str(exc), "captured_at": utc_now()}

    text = raw.decode("gb18030", "ignore")
    fixtures = parse_500_jczq_html(text, source=url)
    return fixtures, {"source": url, "count": len(fixtures), "error": None, "captured_at": utc_now()}


def parse_500_jczq_html(text: str, source: str = JZQ_URL) -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for match in re.finditer(r'<tr\b(?P<attrs>[^>]*class="[^"]*\bbet-tb-tr\b[^"]*"[^>]*)>(?P<body>.*?)</tr>', text, re.S | re.I):
        attrs = parse_attrs(match.group("attrs"))
        body = match.group("body")
        home = attrs.get("data-homesxname") or ""
        away = attrs.get("data-awaysxname") or ""
        if not home or not away:
            continue
        odds_summary = parse_bet_buttons(body)
        handicap = parse_float(attrs.get("data-rangqiu"))
        fixture_id = attrs.get("data-fixtureid") or attrs.get("data-id") or ""
        match_num = attrs.get("data-matchnum") or ""
        fixture = {
            "match_id": f"500_{fixture_id or stable_key(home, away, attrs.get('data-matchdate'), attrs.get('data-matchtime'))}",
            "source": "500彩票网竞彩备份源",
            "competition": attrs.get("data-simpleleague") or "竞彩足球",
            "stage": match_num,
            "home_team": home,
            "away_team": away,
            "kickoff": kickoff(attrs.get("data-matchdate"), attrs.get("data-matchtime")),
            "status": "finished" if attrs.get("data-isend") == "1" else "scheduled",
            "home_score": None,
            "away_score": None,
            "venue": None,
            "backup_source": "500彩票网",
            "backup_match_num": match_num,
            "backup_fixture_id": fixture_id,
            "backup_buy_end_time": attrs.get("data-buyendtime"),
            "backup_handicap": handicap,
            "backup_play_status": parse_subactive(attrs.get("data-subactive", "")),
            "odds_summary": odds_summary,
            "raw_attrs": attrs,
        }
        fixtures.append(fixture)
    return fixtures


def parse_attrs(value: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for key, quote, raw in re.findall(r'([\w:-]+)\s*=\s*([\'"])(.*?)\2', value, re.S):
        attrs[key.lower()] = unescape(raw.strip())
    return attrs


def parse_bet_buttons(body: str) -> list[dict[str, Any]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for bet in re.finditer(r'<p\b(?P<attrs>[^>]*class="[^"]*\bbetbtn\b[^"]*"[^>]*)>', body, re.S | re.I):
        attrs = parse_attrs(bet.group("attrs"))
        market = TYPE_MARKET_MAP.get(attrs.get("data-type", ""))
        selection = SELECTION_MAP.get(attrs.get("data-value", ""), attrs.get("data-value", ""))
        sp = attrs.get("data-sp")
        if not market or not selection or not sp:
            continue
        rows.setdefault(market, []).append({"name": selection if market == "胜平负" else f"让{selection}", "sp": sp})
    return [{"play": market, "options": options} for market, options in rows.items() if options]


def parse_subactive(value: str) -> dict[str, str]:
    output: dict[str, str] = {}
    for part in (value or "").split(","):
        if ":" not in part:
            continue
        key, val = part.split(":", 1)
        output[key] = val
    return output


def kickoff(match_date: str | None, match_time: str | None) -> str | None:
    if not match_date or not match_time:
        return None
    return f"{match_date}T{match_time}:00+08:00"


def stable_key(home: str, away: str, date: str | None, time: str | None) -> str:
    return re.sub(r"\W+", "_", f"{home}_{away}_{date or ''}_{time or ''}")


def parse_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace("+", "").strip())
    except (TypeError, ValueError):
        return None


def find_backup_fixture(match_or_fixture: dict[str, Any], backup_fixtures: list[dict[str, Any]]) -> dict[str, Any] | None:
    home = normalize_name(str(match_or_fixture.get("home_team", "")))
    away = normalize_name(str(match_or_fixture.get("away_team", "")))
    kickoff_date = str(match_or_fixture.get("kickoff") or "")[:10]
    for fixture in backup_fixtures:
        if normalize_name(str(fixture.get("home_team", ""))) != home:
            continue
        if normalize_name(str(fixture.get("away_team", ""))) != away:
            continue
        if kickoff_date and str(fixture.get("kickoff") or "")[:10] != kickoff_date:
            continue
        return fixture
    return None


def play_options(summary: list[dict[str, Any]] | None, play: str) -> dict[str, float]:
    for row in summary or []:
        if row.get("play") != play and not str(row.get("play", "")).startswith(play):
            continue
        output: dict[str, float] = {}
        for option in row.get("options", []) or []:
            name = str(option.get("name") or "")
            try:
                output[name] = float(option.get("sp"))
            except (TypeError, ValueError):
                continue
        return output
    return {}


def compare_official_backup(
    official: dict[str, Any] | None,
    backup: dict[str, Any] | None,
    h2h_sp_tolerance: float = 0.04,
    handicap_sp_tolerance: float = 0.10,
) -> dict[str, Any]:
    if not official and not backup:
        return {
            "level": "D",
            "status": "缺少竞彩字段",
            "can_recommend_handicap": False,
            "notes": ["官方源和500备份源都未拿到。"],
        }
    if official and not backup:
        return {
            "level": "B",
            "status": "官方单源可用",
            "can_recommend_handicap": True,
            "notes": ["500备份源未匹配到该场，以下单前官方计算器为准。"],
        }
    if backup and not official:
        return {
            "level": "C",
            "status": "仅备份源可用",
            "can_recommend_handicap": False,
            "notes": ["体彩官方未拿到，500可作为预测参考，但让球下注前必须人工核对官方。"],
        }

    notes: list[str] = []
    structural_conflicts: list[str] = []
    assert official is not None and backup is not None
    if normalize_name(str(official.get("home_team"))) != normalize_name(str(backup.get("home_team"))) or normalize_name(str(official.get("away_team"))) != normalize_name(str(backup.get("away_team"))):
        structural_conflicts.append("主客队不一致")
    if str(official.get("kickoff") or "")[:16] != str(backup.get("kickoff") or "")[:16]:
        structural_conflicts.append("开赛时间不一致")
    official_h = handicap_from_summary(official.get("odds_summary")) if official.get("odds_summary") else official.get("sporttery_handicap")
    backup_h = backup.get("backup_handicap")
    if official_h is not None and backup_h is not None and float(official_h) != float(backup_h):
        structural_conflicts.append(f"让球不一致：官方{official_h}，500 {backup_h}")
    if official.get("sporttery_match_num") and backup.get("backup_match_num") and official.get("sporttery_match_num") != backup.get("backup_match_num"):
        structural_conflicts.append(f"赛事编号不一致：官方{official.get('sporttery_match_num')}，500 {backup.get('backup_match_num')}")

    official_h2h = play_options(official.get("odds_summary"), "胜平负")
    backup_h2h = play_options(backup.get("odds_summary"), "胜平负")
    sp_notes: list[str] = []
    sp_alerts = compare_sp(official_h2h, backup_h2h, h2h_sp_tolerance, "胜平负", sp_notes)
    official_hhad = play_options(official.get("odds_summary"), "让球")
    backup_hhad = play_options(backup.get("odds_summary"), "让球胜平负")
    sp_alerts.extend(compare_sp(official_hhad, backup_hhad, handicap_sp_tolerance, "让球胜平负", sp_notes))

    if structural_conflicts:
        return {
            "level": "E",
            "status": "字段冲突，需人工核对",
            "can_recommend_handicap": False,
            "official_handicap": official_h,
            "backup_handicap": backup_h,
            "notes": structural_conflicts,
        }
    notes.append("官方源与500备份源主客队、时间、赛事编号和让球数一致。")
    if sp_alerts:
        notes.extend(sp_alerts)
        notes.append("以上属于SP波动提示，不是赛事字段冲突；下单和收益测算以官方体彩最终SP为准。")
    elif sp_notes:
        notes.extend(sp_notes)
    else:
        notes.append("胜平负和让球SP在容差内一致。")
    return {
        "level": "A" if not sp_alerts else "A-",
        "status": "官方+500结构一致" if sp_alerts else "官方+500一致",
        "can_recommend_handicap": True,
        "official_handicap": official_h,
        "backup_handicap": backup_h,
        "notes": notes,
    }


def handicap_from_summary(summary: list[dict[str, Any]] | None) -> float | None:
    for row in summary or []:
        text = str(row.get("play") or "")
        match = re.search(r"让球\(([+-]?\d+(?:\.\d+)?)\)", text)
        if match:
            return parse_float(match.group(1))
    return None


def compare_sp(official: dict[str, float], backup: dict[str, float], tolerance: float, label: str, notes: list[str] | None = None) -> list[str]:
    out: list[str] = []
    for name, official_value in official.items():
        backup_value = backup.get(name)
        if backup_value is None:
            out.append(f"500缺少{label}{name}SP")
            continue
        diff = abs(official_value - backup_value)
        if diff > tolerance:
            out.append(f"{label}{name}SP差异过大：官方{official_value:.2f}，500 {backup_value:.2f}")
        elif diff > 0.001 and notes is not None:
            notes.append(f"{label}{name}SP有小幅差异：官方{official_value:.2f}，500 {backup_value:.2f}，下单以官方为准。")
    return out
