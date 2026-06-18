from __future__ import annotations

import math
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from .source_registry import load_source_health, load_sources
from .standings_client import find_group_context


SCENARIO_LABELS = {
    "baseline": "基准模型",
    "market": "市场校准模型",
    "live": "临场信息模型",
    "conservative": "保守节奏模型",
    "open": "开放节奏模型",
    "upset": "爆冷情景模型",
}


UPSET_RULES = {
    "strong_single_point": ("强队进攻依赖单点", 1.5),
    "strong_low_block_problem": ("强队破密防能力不足", 2.5),
    "strong_slow_center_backs": ("强队中卫速度慢", 2.0),
    "strong_dm_protection_gap": ("强队后腰保护不足", 2.0),
    "strong_fullbacks_high": ("强队边后卫压太高", 1.5),
    "strong_fatigue": ("强队体能 / 赛程吃亏", 2.0),
    "strong_low_motivation": ("强队动机不足或可能轮换", 2.0),
    "underdog_low_block": ("弱队低位防守好", 2.0),
    "underdog_goalkeeper": ("弱队门将状态好", 1.5),
    "underdog_set_piece": ("弱队定位球强", 1.6),
    "underdog_counter_speed": ("弱队反击速度快", 1.8),
    "underdog_physicality": ("弱队身体对抗强", 1.2),
    "weather_pitch_against_technical": ("天气 / 场地不利技术流", 1.0),
    "referee_lenient": ("裁判尺度偏宽", 0.8),
    "early_event_risk": ("早期红牌 / 点球 / 乌龙风险", 1.0),
}


DIMENSIONS = [
    ("strength", "基础实力 / Elo / 市场概率", 18),
    ("fifa_ranking", "FIFA 世界排名差", 6),
    ("formal_competition_strength", "世界杯预选赛 / 洲际杯正式赛", 10),
    ("process", "xG / xGA / 射门质量", 16),
    ("authority_side_strength", "权威侧面实力评分", 8),
    ("match_process_rating", "赛中/赛后过程表现", 8),
    ("lineup", "阵容伤停与首发", 12),
    ("tactics", "战术相克与比赛形态", 12),
    ("schedule", "赛程 / 体能 / 旅行 / 气候", 7),
    ("set_piece_keeper", "定位球与门将", 8),
    ("upset", "爆冷触发器", 7),
    ("motivation", "积分形势 / 比赛动机", 4),
    ("referee", "裁判尺度 / 红牌点球变量", 2),
]


AUTHORITY_SOURCE_WEIGHTS = {
    "fifa_tsg": 1.00,
    "uefa_report": 0.95,
    "opta": 0.95,
    "stats_perform": 0.95,
    "statsbomb": 0.90,
    "wyscout": 0.88,
    "cies": 0.82,
    "the_athletic": 0.76,
    "bbc": 0.72,
    "guardian": 0.70,
    "sky": 0.66,
    "lequipe": 0.66,
    "zhang_lu": 0.58,
    "zhan_jun": 0.52,
    "cctv": 0.60,
    "football_news_cn": 0.55,
}


CONFEDERATION_BASE_STRENGTH = {
    "UEFA": 0.45,
    "CONMEBOL": 0.42,
    "CAF": 0.16,
    "CONCACAF": 0.10,
    "AFC": 0.08,
    "OFC": -0.28,
}


FORMAL_STAGE_BONUS = {
    "winner": 0.85,
    "champion": 0.85,
    "finalist": 0.70,
    "semifinal": 0.52,
    "quarterfinal": 0.34,
    "round16": 0.18,
    "group": 0.0,
}


OPEN_GAME_RULES = {
    "favorite_multi_finishers": ("强队多终结点/双前锋冲击", 1.2),
    "favorite_set_piece_edge": ("强队定位球和空中球优势", 0.8),
    "underdog_chase_fragility": ("弱队落后后防线容易拉开", 1.1),
    "underdog_high_line_when_trailing": ("弱队追分时会前压露身后", 0.8),
    "qualifying_defense_schedule_noise": ("弱队防守样本对手强度不足", 0.9),
    "late_game_fitness_gap": ("后段体能和替补强度差", 0.8),
    "must_chase_goal_difference": ("积分/净胜球导致后段必须追", 0.7),
}


@dataclass
class PredictionResult:
    scenario: str
    label: str
    probabilities: dict[str, float]
    expected_goals: dict[str, float]
    top_scores: list[dict[str, Any]]
    score_grid: list[dict[str, Any]]
    goal_distribution: list[dict[str, Any]]
    total_goals: dict[str, Any]
    over_under_lines: list[dict[str, Any]]
    over_25: float
    btts: float
    confidence: int
    notes: list[str]


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_probs(probs: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, v) for v in probs.values())
    if total <= 0:
        return {"home": 1 / 3, "draw": 1 / 3, "away": 1 / 3}
    return {k: max(0.0, v) / total for k, v in probs.items()}


def elo_probabilities(home_elo: float, away_elo: float, neutral: bool = True) -> dict[str, float]:
    home_advantage = 0 if neutral else 55
    diff = home_elo + home_advantage - away_elo
    home_no_draw = 1 / (1 + 10 ** (-diff / 400))
    draw = clamp(0.29 - abs(diff) * 0.00016, 0.18, 0.34)
    non_draw = 1 - draw
    return normalize_probs(
        {
            "home": non_draw * home_no_draw,
            "draw": draw,
            "away": non_draw * (1 - home_no_draw),
        }
    )


def implied_probabilities(odds: dict[str, float]) -> dict[str, float] | None:
    if not odds or any(v <= 1 for v in odds.values()):
        return None
    implied = {k: 1 / v for k, v in odds.items()}
    return normalize_probs(implied)


def blend_probs(base: dict[str, float], other: dict[str, float] | None, weight: float) -> dict[str, float]:
    if not other:
        return base
    return normalize_probs({k: base[k] * (1 - weight) + other[k] * weight for k in base})


def estimate_expected_goals(match: dict[str, Any], probs: dict[str, float], mode: str) -> dict[str, float]:
    manual = match.get("expected_goals", {})
    if "home" in manual and "away" in manual:
        home_xg = float(manual["home"])
        away_xg = float(manual["away"])
    else:
        edge = probs["home"] - probs["away"]
        total = 2.42 + clamp(match.get("tempo_score", 0), -3, 3) * 0.08
        home_xg = clamp(total / 2 + edge * 1.15, 0.35, 3.4)
        away_xg = clamp(total - home_xg, 0.25, 3.1)

    formal_strength = formal_competition_strength_score(match)
    if abs(formal_strength) >= 0.15:
        formal_effect = clamp(formal_strength / 2.5, -1, 1)
        home_xg *= 1 + 0.055 * formal_effect
        away_xg *= 1 - 0.045 * formal_effect
    fifa_strength = fifa_ranking_score(match)
    if abs(fifa_strength) >= 0.15:
        rank_effect = clamp(fifa_strength / 2, -1, 1)
        home_xg *= 1 + 0.030 * rank_effect
        away_xg *= 1 - 0.025 * rank_effect

    open_profile = open_game_profile(match, probs, {"home": home_xg, "away": away_xg})
    open_effect = clamp(open_profile["score"] / 5, 0, 1)
    if open_effect > 0:
        favorite = open_profile["favorite_side"]
        total_boost = 1 + 0.08 * open_effect
        if favorite == "home":
            home_xg *= 1 + 0.10 * open_effect
            away_xg *= total_boost if open_profile.get("chase_fragility") else 1 + 0.04 * open_effect
        else:
            away_xg *= 1 + 0.10 * open_effect
            home_xg *= total_boost if open_profile.get("chase_fragility") else 1 + 0.04 * open_effect

    if mode == "conservative":
        home_xg *= 0.84
        away_xg *= 0.84
    elif mode == "open":
        home_xg *= 1.16
        away_xg *= 1.16
    elif mode == "upset":
        favorite = "home" if probs["home"] >= probs["away"] else "away"
        if favorite == "home":
            home_xg *= 0.82
            away_xg *= 1.12
        else:
            away_xg *= 0.82
            home_xg *= 1.12

    return {"home": round(clamp(home_xg, 0.2, 4.2), 3), "away": round(clamp(away_xg, 0.15, 3.8), 3)}


def lambda_adjustment_profile(match: dict[str, Any], probs: dict[str, float], xg: dict[str, float]) -> dict[str, Any]:
    dimensions = match.get("dimension_scores", {})
    configured = match.get("value_feature_scores", {})

    def score(name: str, fallback: float = 0.0) -> float:
        return clamp(float(configured.get(name, dimensions.get(name, fallback))), -2, 2)

    formal = formal_competition_strength_score(match)
    lineup = score("lineup")
    schedule = score("schedule")
    tactics = score("tactics")
    set_piece = score("set_piece_keeper")
    motivation = score("motivation")
    tempo = clamp(float(match.get("tempo_score", 0)), -3, 3)
    favorite = "home" if probs.get("home", 0) >= probs.get("away", 0) else "away"
    variance = variance_profile(match, probs, xg)
    one_goal_delta = one_goal_bias_delta(
        {
            "handicap": match.get("sporttery_handicap"),
            "model_probs": probs,
            "xg": xg,
            "favorite_side": favorite,
        }
    )
    return {
        "formal_competition_strength": round(formal, 3),
        "fifa_ranking": round(fifa_ranking_score(match), 3),
        "lineup": round(lineup, 3),
        "schedule": round(schedule, 3),
        "tactics": round(tactics, 3),
        "set_piece_keeper": round(set_piece, 3),
        "motivation": round(motivation, 3),
        "tempo": round(tempo, 3),
        "variance_profile": variance,
        "one_goal_bias_delta": round(one_goal_delta, 3),
    }


def trigger_weight(value: Any, base_weight: float) -> tuple[bool, float, float]:
    confidence = 1.0
    if isinstance(value, dict):
        enabled = bool(value.get("enabled", True))
        strength = float(value.get("strength", 1.0))
        confidence = float(value.get("confidence", 1.0))
        return enabled, base_weight * strength * confidence, confidence
    if isinstance(value, (int, float)):
        return value > 0, base_weight * float(value), confidence
    return bool(value), base_weight if value else 0.0, confidence


def open_game_profile(
    match: dict[str, Any],
    probs: dict[str, float] | None = None,
    xg: dict[str, float] | None = None,
) -> dict[str, Any]:
    triggers = match.get("open_game_triggers", {})
    active = []
    for key, (label, base_weight) in OPEN_GAME_RULES.items():
        enabled, weight, confidence = trigger_weight(triggers.get(key, False), base_weight)
        if enabled:
            active.append({"key": key, "label": label, "weight": round(weight, 2), "confidence": confidence})

    tempo = clamp(float(match.get("tempo_score", 0)), -3, 3)
    if tempo > 0.8:
        active.append({"key": "tempo", "label": "赛前节奏偏开放", "weight": round(tempo * 0.45, 2), "confidence": 1.0})

    score = sum(item["weight"] for item in active)
    favorite_side = "home"
    if probs and probs.get("away", 0) > probs.get("home", 0):
        favorite_side = "away"
    elif not probs and float(match.get("away_elo", 1800)) > float(match.get("home_elo", 1800)):
        favorite_side = "away"
    chase_fragility = any(item["key"] in {"underdog_chase_fragility", "underdog_high_line_when_trailing"} for item in active)
    if score < 1.5:
        level = "低"
    elif score < 3.0:
        level = "中低"
    elif score < 4.5:
        level = "中高"
    else:
        level = "高"
    return {
        "score": round(score, 2),
        "level": level,
        "active": active,
        "favorite_side": favorite_side,
        "chase_fragility": chase_fragility,
        "xg_total": round((xg or {}).get("home", 0) + (xg or {}).get("away", 0), 3) if xg else None,
    }


def poisson(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def negative_binomial(k: int, mean: float, dispersion: float) -> float:
    if dispersion <= 0:
        return poisson(k, mean)
    r = max(0.8, 1 / dispersion)
    p = r / (r + max(mean, 0.001))
    return math.exp(
        math.lgamma(k + r)
        - math.lgamma(r)
        - math.lgamma(k + 1)
        + r * math.log(p)
        + k * math.log(1 - p)
    )


def dixon_coles_multiplier(home_goals: int, away_goals: int, home_xg: float, away_xg: float, mode: str) -> float:
    rho_by_mode = {
        "baseline": -0.035,
        "market": -0.035,
        "live": -0.035,
        "conservative": -0.060,
        "upset": -0.055,
        "open": -0.015,
    }
    rho = rho_by_mode.get(mode, -0.035)
    if home_goals == 0 and away_goals == 0:
        return clamp(1 - home_xg * away_xg * rho, 0.85, 1.20)
    if home_goals == 0 and away_goals == 1:
        return clamp(1 + home_xg * rho, 0.85, 1.12)
    if home_goals == 1 and away_goals == 0:
        return clamp(1 + away_xg * rho, 0.85, 1.12)
    if home_goals == 1 and away_goals == 1:
        return clamp(1 - rho, 0.92, 1.14)
    return 1.0


def variance_profile(match: dict[str, Any], probs: dict[str, float], xg: dict[str, float], handicap: int | None = None) -> dict[str, Any]:
    open_profile = open_game_profile(match, probs, xg)
    upset = upset_profile(match)
    if handicap is None:
        handicap = match.get("sporttery_handicap")
    stall_profile = favorite_stall_profile(match, probs, xg, handicap)
    tempo = clamp(float(match.get("tempo_score", 0)), -3, 3)
    total = float(xg.get("home", 0)) + float(xg.get("away", 0))
    prob_gap = abs(float(probs.get("home", 0)) - float(probs.get("away", 0)))

    overdispersion = 0.0
    low_score_shrink = 0.0
    reasons = []
    if open_profile["score"] >= 2.5:
        overdispersion += 0.10 + open_profile["score"] * 0.018
        reasons.append("开放节奏提高比分尾部")
    if upset["score"] >= 4:
        overdispersion += 0.08
        reasons.append("爆冷触发器提高方差")
    if total >= 3.15 and prob_gap >= 0.45:
        overdispersion += 0.08
        reasons.append("强弱深盘保留大比分尾部")
    if tempo < -0.8 or total <= 2.2:
        low_score_shrink += 0.08 + min(0.08, abs(tempo) * 0.025)
        reasons.append("低节奏/低总进球压缩方差")
    if stall_profile["score"] >= 0.45:
        stall_effect = stall_profile["score"]
        low_score_shrink += 0.06 + stall_effect * 0.06
        overdispersion *= 1 - min(0.35, stall_effect * 0.35)
        reasons.append("热门降温触发，增加平局/小比分保护")

    return {
        "overdispersion": round(clamp(overdispersion, 0, 0.34), 3),
        "low_score_shrink": round(clamp(low_score_shrink, 0, 0.20), 3),
        "draw_low_score_boost": round(clamp(stall_profile["score"] * 0.16, 0, 0.16), 3),
        "favorite_cover_cooldown": round(clamp(stall_profile["score"] * 0.18, 0, 0.18), 3),
        "favorite_stall_profile": stall_profile,
        "reasons": reasons,
    }


def one_goal_bias_delta(context: dict[str, Any] | None) -> float:
    if not context:
        return 0.0
    handicap = context.get("handicap")
    probs = context.get("model_probs") or {}
    xg = context.get("xg") or {}
    if handicap is None or abs(int(handicap)) != 1:
        return 0.0
    favorite = context.get("favorite_side")
    prob_gap = abs(float(probs.get("home", 0)) - float(probs.get("away", 0)))
    xg_gap = abs(float(xg.get("home", 0)) - float(xg.get("away", 0)))
    total = float(xg.get("home", 0)) + float(xg.get("away", 0))
    if prob_gap < 0.18 or xg_gap > 1.35 or total > 3.05:
        return 0.0
    if favorite in {"home", "away"}:
        return 0.08 if total >= 2.15 else 0.12
    return 0.0


def deep_favorite_context(match: dict[str, Any], probs: dict[str, float], xg: dict[str, float], handicap: int | None) -> dict[str, Any]:
    elo_gap = abs(float(match.get("home_elo", 1800)) - float(match.get("away_elo", 1800)))
    prob_gap = abs(float(probs.get("home", 0)) - float(probs.get("away", 0)))
    xg_gap = abs(float(xg.get("home", 0)) - float(xg.get("away", 0)))
    favorite_side = "home" if probs.get("home", 0) >= probs.get("away", 0) else "away"
    deep = (
        handicap is not None
        and abs(int(handicap)) >= 2
        and (
            elo_gap >= 300
            or prob_gap >= 0.50
            or xg_gap >= 1.75
        )
    )
    return {"deep_favorite_profile": deep, "favorite_side": favorite_side}


def favorite_stall_profile(match: dict[str, Any], probs: dict[str, float], xg: dict[str, float], handicap: int | None = None) -> dict[str, Any]:
    """Prematch trigger for favorite-cooldown, low draw, and score protection."""
    favorite_side = "home" if probs.get("home", 0) >= probs.get("away", 0) else "away"
    prob_gap = abs(float(probs.get("home", 0)) - float(probs.get("away", 0)))
    xg_gap = abs(float(xg.get("home", 0)) - float(xg.get("away", 0)))
    total_xg = float(xg.get("home", 0)) + float(xg.get("away", 0))
    triggers = match.get("upset_triggers", {}) or {}
    opening_round = bool(match.get("opening_round") or match.get("group_first_match") or match.get("round") in {"1", 1, "首轮"})

    low_block_keys = {
        "strong_low_block_problem",
        "underdog_low_block",
        "underdog_goalkeeper",
        "strong_low_motivation",
        "early_event_risk",
        "favorite_finishing_risk",
    }
    active_keys: list[str] = []
    trigger_score = 0.0
    for key in low_block_keys:
        value = triggers.get(key)
        if isinstance(value, dict):
            enabled = bool(value.get("enabled", True))
            strength = float(value.get("strength", 1.0))
            confidence = float(value.get("confidence", 1.0))
            amount = strength * confidence
        elif isinstance(value, (int, float)):
            enabled = value > 0
            amount = float(value)
        else:
            enabled = bool(value)
            amount = 1.0 if enabled else 0.0
        if enabled:
            active_keys.append(key)
            trigger_score += amount

    deep_market = handicap is not None and abs(int(handicap)) >= 2
    favorite_heavy = prob_gap >= 0.34 or xg_gap >= 1.05 or deep_market
    low_total = total_xg <= 2.85
    score = 0.0
    if favorite_heavy:
        score += 0.22
    if deep_market:
        score += 0.18
    if low_total:
        score += 0.18
    if opening_round:
        score += 0.10
    score += min(0.28, trigger_score * 0.07)

    reasons = []
    if favorite_heavy:
        reasons.append("热门方向过热，不能只按强队大胜处理")
    if deep_market:
        reasons.append("让球较深，需要防不穿盘")
    if low_total:
        reasons.append("总进球预期不高，需保护0:0/1:1/小胜")
    if opening_round:
        reasons.append("小组首轮/早段赛事，强队更容易先求稳")
    if active_keys:
        reasons.append("存在低位防守、门将、战意或临场波动触发器")

    return {
        "score": round(clamp(score, 0, 1), 3),
        "favorite_side": favorite_side,
        "active_keys": active_keys,
        "opening_round": opening_round,
        "favorite_heavy": favorite_heavy,
        "low_total": low_total,
        "reasons": reasons,
    }


SIDE_SIGNAL_FIELDS = (
    ("folk_signal", "八卦/周易"),
    ("zhouyi_signal", "周易"),
    ("bagua_signal", "八卦"),
    ("qimen_signal", "奇门遁甲"),
    ("ziwei_signal", "紫微斗数"),
)


def side_signal_raw_items(match: dict[str, Any]) -> list[tuple[str, Any]]:
    items: list[tuple[str, Any]] = []
    raw_list = match.get("side_signals")
    if isinstance(raw_list, list):
        for raw in raw_list:
            track = "支线"
            if isinstance(raw, dict):
                track = str(raw.get("track") or raw.get("type") or track)
            items.append((track, raw))
    for field, track in SIDE_SIGNAL_FIELDS:
        if match.get(field):
            items.append((track, match[field]))
    return items


def side_signal_effect(label: str, note: str) -> tuple[str, str]:
    text = f"{label} {note}"
    if any(word in text for word in ("不败", "不输", "受让不败", "受让守住")):
        return "non_loss_protection", "提示一方不败/受让守住"
    if any(word in text for word in ("不穿盘", "打不穿", "防穿", "赢球不赢盘", "输盘", "守盘", "受让方向", "受让方")):
        return "no_cover_protection", "提示热门不穿盘"
    if any(word in text for word in ("防平", "平局", "不稳", "不胜")):
        return "draw_protection", "提示防平/强队不稳"
    if any(word in text for word in ("爆冷", "防冷", "冷门", "受克", "弱队")):
        return "upset_protection", "提示可能爆冷"
    if any(word in text for word in ("小球", "低比分", "少球")):
        return "low_total", "提示小球/低比分"
    if any(word in text for word in ("大球", "多球", "进球多")):
        return "high_total", "提示大球/进球多"
    if any(word in text for word in ("大胜", "穿盘", "强队稳", "支持强队")):
        return "favorite_support", "支持强队方向"
    if any(word in text for word in ("大负", "溃败", "惨败")):
        return "favorite_big_margin", "提示可能大比分分差"
    if any(word in text for word in ("冲突", "相反", "反向")):
        return "conflict", "与数据模型可能冲突"
    return "watch_only", "信号不明确，仅作观察"


def side_signal_display(effect: str) -> str:
    return {
        "non_loss_protection": "提示一方不败/受让守住",
        "no_cover_protection": "提示热门不穿盘",
        "draw_protection": "提示防平/强队不稳",
        "upset_protection": "提示可能爆冷",
        "low_total": "提示小球/低比分",
        "high_total": "提示大球/进球多",
        "favorite_support": "支持强队方向",
        "favorite_big_margin": "提示可能大比分分差",
        "conflict": "与数据模型可能冲突",
        "watch_only": "信号不明确，仅作观察",
    }.get(effect, "信号不明确，仅作观察")


def normalize_side_signal_text(value: Any) -> str:
    return (
        str(value or "")
        .replace(" ", "")
        .replace("(", "")
        .replace(")", "")
        .replace("（", "")
        .replace("）", "")
    )


def side_signal_target(match: dict[str, Any], text: str) -> tuple[str | None, str | None]:
    normalized = normalize_side_signal_text(text)
    teams = [
        ("home", match.get("home_team"), match.get("home_aliases") or []),
        ("away", match.get("away_team"), match.get("away_aliases") or []),
    ]
    for side, team, aliases in teams:
        names = [team, *aliases]
        if any(name and normalize_side_signal_text(name) in normalized for name in names):
            return side, str(team)
    if any(word in normalized for word in ("主队", "主场")):
        return "home", str(match.get("home_team"))
    if any(word in normalized for word in ("客队", "客场")):
        return "away", str(match.get("away_team"))
    return None, None


def parse_side_signal(track: str, raw: Any, match: dict[str, Any] | None = None) -> dict[str, Any]:
    if not raw:
        return {"enabled": False, "label": "无民间信号", "effect": "none", "confidence": 0.0, "note": ""}
    if isinstance(raw, str):
        label = raw
        confidence = 0.3
        source = track
        note = raw
    else:
        label = str(raw.get("label") or raw.get("tag") or raw.get("effect") or "民间信号")
        confidence = float(raw.get("confidence", raw.get("weight", 0.3)) or 0.3)
        source = str(raw.get("source") or track)
        note = str(raw.get("note") or raw.get("reason") or label)
    explicit_effect = str(raw.get("effect", "")) if isinstance(raw, dict) else ""
    effect, display = side_signal_effect(label, note)
    if explicit_effect in {
        "non_loss_protection",
        "no_cover_protection",
        "draw_protection",
        "upset_protection",
        "low_total",
        "high_total",
        "favorite_support",
        "favorite_big_margin",
        "conflict",
        "watch_only",
    }:
        effect = explicit_effect
        display = side_signal_display(effect)
    target_side, target_team = side_signal_target(match, f"{label} {note}") if match else (None, None)
    return {
        "enabled": True,
        "track": track,
        "source": source,
        "label": label,
        "effect": effect,
        "target_side": target_side,
        "target_team": target_team,
        "confidence": round(clamp(confidence, 0, 1), 3),
        "display": f"{track}{display}",
        "note": note,
        "parallel_only": True,
        "warning": "支线信号是平行分析线，不参与核心概率、EV和Kelly计算",
    }


def side_signal_profiles(match: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = [parse_side_signal(track, raw, match) for track, raw in side_signal_raw_items(match)]
    return [profile for profile in profiles if profile.get("enabled")]


def folk_signal_profile(match: dict[str, Any]) -> dict[str, Any]:
    profiles = side_signal_profiles(match)
    if profiles:
        return sorted(profiles, key=lambda item: item.get("confidence", 0), reverse=True)[0]
    return {"enabled": False, "label": "无民间信号", "effect": "none", "confidence": 0.0, "note": ""}


def side_signal_result_label(effect: str, target_team: str | None) -> str:
    if effect == "non_loss_protection":
        return f"{target_team}不败" if target_team else "一方不败/受让守住"
    if effect == "no_cover_protection":
        return "热门不穿盘"
    if effect == "draw_protection":
        return "防平"
    if effect == "upset_protection":
        return f"{target_team}方向防冷" if target_team else "防冷"
    if effect == "low_total":
        return "低比分/小球"
    if effect == "high_total":
        return "进球偏多"
    if effect == "favorite_big_margin":
        return "大比分分差"
    if effect == "favorite_support":
        return f"支持{target_team}" if target_team else "支持强队"
    return "仅观察"


def side_signal_handicap_label(effects: set[str], target_team: str | None) -> str:
    if "no_cover_protection" in effects:
        return "让负/让平保护"
    if "non_loss_protection" in effects:
        return f"{target_team or '受让方'}受让方向"
    if "draw_protection" in effects or "upset_protection" in effects:
        return "让负/防冷保护"
    if "favorite_big_margin" in effects:
        return "让胜/大胜尾部"
    return "无明确让球支线"


def main_side_comparison(
    match: dict[str, Any],
    main_label: str,
    score_labels: list[str],
    effects: set[str],
    signal: dict[str, Any],
    alignment: str,
    betting_checks: list[str],
) -> list[dict[str, str]]:
    target_team = signal.get("target_team")
    primary_effect = str(signal.get("effect") or "watch_only")
    side_result = side_signal_result_label(primary_effect, target_team)
    if alignment == "冲突观察":
        result_relation = "冲突：主线偏热门，支线防冷/不败"
    elif alignment == "可能一致":
        result_relation = "一致：支线增强方向但不加仓"
    elif alignment == "风险提醒":
        result_relation = "部分一致：主线方向不变，支线提示保护"
    else:
        result_relation = alignment or "仅观察"

    return [
        {
            "dimension": "赛果方向",
            "main": main_label,
            "side": side_result,
            "relation": result_relation,
        },
        {
            "dimension": "让球方向",
            "main": "按官方让球和比分矩阵决定",
            "side": side_signal_handicap_label(effects, target_team),
            "relation": "只检查让球保护，不改主胜率",
        },
        {
            "dimension": "比分/进球",
            "main": " / ".join(score_labels[:3]) if score_labels else "待定",
            "side": "低比分/小球" if "low_total" in effects or effects & {"non_loss_protection", "no_cover_protection", "draw_protection"} else ("高进球/大比分尾部" if effects & {"high_total", "favorite_big_margin"} else "无明确比分支线"),
            "relation": "支线用于扩充比分池，不单压一个比分",
        },
        {
            "dimension": "下注落点",
            "main": "以EV、SP和风险分筛选候选",
            "side": "、".join(betting_checks) if betting_checks else "不生成支线可买项",
            "relation": "支线只给检查项，不能直接变主推",
        },
    ]


def folk_parallel_summary(match: dict[str, Any], model_probs: dict[str, float] | None = None) -> dict[str, Any]:
    return folk_parallel_summary_with_context(match, model_probs)


def folk_parallel_summary_with_context(
    match: dict[str, Any],
    model_probs: dict[str, float] | None = None,
    main_label: str | None = None,
    score_labels: list[str] | None = None,
) -> dict[str, Any]:
    tracks = side_signal_profiles(match)
    signal = sorted(tracks, key=lambda item: item.get("confidence", 0), reverse=True)[0] if tracks else folk_signal_profile(match)
    if not signal.get("enabled"):
        return {
            **signal,
            "tracks": [],
            "alignment": "未提供",
            "model_relation": "本场没有录入支线标签",
            "side_prediction": "未录入支线预测",
            "betting_advice": "不生成支线下注建议",
            "betting_checks": [],
            "comparison": [
                {"dimension": "赛果方向", "main": main_label or "按主线模型", "side": "未录入", "relation": "无支线对比"},
                {"dimension": "下注落点", "main": "按EV、SP和风险分筛选", "side": "未录入", "relation": "只看主线"},
            ],
            "advice_boundary": "支线为空，按数据模型和官方SP判断",
            "action_hint": "按数据模型和官方SP判断",
        }
    effects = {item.get("effect") for item in tracks} or {signal.get("effect")}
    leader = None
    leader_label = "待定"
    if model_probs:
        leader = max(model_probs, key=lambda key: model_probs[key])
        leader_label = {"home": match["home_team"], "draw": "平局", "away": match["away_team"]}.get(leader, "待定")
    target_team = signal.get("target_team")
    target_side = signal.get("target_side")
    if "non_loss_protection" in effects and target_team:
        side_prediction = f"支线独立判断：{target_team}不败或受让守住"
    elif "no_cover_protection" in effects:
        side_prediction = "支线独立判断：热门方可能赢球但不穿盘"
    elif "draw_protection" in effects:
        side_prediction = "支线独立判断：防平，强队稳定性不足"
    elif "upset_protection" in effects:
        side_prediction = f"支线独立判断：存在爆冷信号{f'，偏向{target_team}' if target_team else ''}"
    elif "low_total" in effects:
        side_prediction = "支线独立判断：低比分、小球倾向"
    elif "high_total" in effects:
        side_prediction = "支线独立判断：节奏可能打开，进球偏多"
    elif "favorite_big_margin" in effects:
        side_prediction = "支线独立判断：存在大比分分差信号"
    elif "favorite_support" in effects:
        side_prediction = f"支线独立判断：支持强势一方{f'，偏向{target_team}' if target_team else ''}"
    else:
        side_prediction = "支线独立判断：信号不明确，仅观察"

    betting_checks: list[str] = []
    if effects & {"non_loss_protection", "draw_protection", "upset_protection"}:
        betting_checks.extend(["胜平负-平", "胜平负-冷门方向", "让球受让方向"])
    if "no_cover_protection" in effects:
        betting_checks.extend(["让球胜平负-让负", "让球胜平负-让平"])
    if "low_total" in effects:
        betting_checks.extend(["总进球0/1/2", "比分0-0/1-1/1-0/0-1"])
    if "high_total" in effects or "favorite_big_margin" in effects:
        betting_checks.extend(["总进球3/4/5+", "大胜比分尾部"])
    betting_checks = list(dict.fromkeys(betting_checks))
    betting_advice = "支线下注建议：只检查" + "、".join(betting_checks) if betting_checks else "支线下注建议：不单独给可买项"
    advice_boundary = "支线不改主模型概率、EV、Kelly和仓位；只作为防冷、比分池和让球保护的检查项"

    target_conflicts_with_model = target_side in {"home", "away"} and leader in {"home", "away"} and target_side != leader
    if "conflict" in effects or target_conflicts_with_model:
        alignment = "冲突观察"
        action_hint = "不改变主推，只在风险区检查防平、防冷和低比分"
    elif "favorite_support" in effects and effects <= {"favorite_support"}:
        alignment = "可能一致" if leader in {"home", "away"} else "与模型不完全一致"
        action_hint = "只增强信心提示，不增加仓位"
    elif effects & {"non_loss_protection", "no_cover_protection", "draw_protection", "upset_protection", "low_total"}:
        alignment = "风险提醒"
        action_hint = "用于检查防平、防冷、防不穿盘或低比分保护"
    elif effects & {"high_total", "favorite_big_margin"}:
        alignment = "节奏提醒"
        action_hint = "用于检查总进球和大比分尾部，仍需盘口支持"
    else:
        alignment = "无明确方向"
        action_hint = "只保留备注，不参与推荐"
    track_text = "；".join(f"{item.get('track')}：{item.get('display')}" for item in tracks[:4])
    resolved_main_label = main_label or leader_label
    comparison = main_side_comparison(match, resolved_main_label, score_labels or [], effects, signal, alignment, betting_checks)
    return {
        **signal,
        "tracks": tracks,
        "alignment": alignment,
        "model_relation": f"数据模型主线：{leader_label}；支线：{track_text or signal.get('display')}",
        "side_prediction": side_prediction,
        "betting_advice": betting_advice,
        "betting_checks": betting_checks,
        "comparison": comparison,
        "advice_boundary": advice_boundary,
        "action_hint": action_hint,
    }


def apply_goal_distribution_adjustments(rows: list[dict[str, Any]], context: dict[str, Any] | None) -> None:
    if not context:
        return
    variance = context.get("variance_profile") or {}
    overdispersion = float(variance.get("overdispersion", 0) or 0)
    low_score_shrink = float(variance.get("low_score_shrink", 0) or 0)
    draw_low_score_boost = float(variance.get("draw_low_score_boost", 0) or 0)
    favorite_cover_cooldown = float(variance.get("favorite_cover_cooldown", 0) or 0)
    favorite = context.get("favorite_side")
    delta = one_goal_bias_delta(context)

    for row in rows:
        h = int(row["home_goals"])
        a = int(row["away_goals"])
        total_goals = h + a
        margin = h - a
        abs_margin = abs(margin)

        if overdispersion > 0 and (total_goals >= 4 or abs_margin >= 3):
            row["probability"] *= 1 + overdispersion * (0.65 + 0.12 * max(0, total_goals - 4))
        if low_score_shrink > 0 and total_goals >= 4:
            row["probability"] *= 1 - low_score_shrink
        if low_score_shrink > 0 and total_goals <= 1:
            row["probability"] *= 1 + low_score_shrink * 0.55
        if draw_low_score_boost > 0:
            if margin == 0 and total_goals <= 2:
                row["probability"] *= 1 + draw_low_score_boost * (1.35 if total_goals <= 2 else 1.0)
            elif total_goals <= 2 and abs_margin <= 1:
                row["probability"] *= 1 + draw_low_score_boost * 0.65
        if favorite_cover_cooldown > 0:
            favorite_big_cover = (
                favorite == "home"
                and margin >= 3
                or favorite == "away"
                and margin <= -3
            )
            if favorite_big_cover:
                row["probability"] *= 1 - favorite_cover_cooldown

        if delta > 0:
            favorite_one_goal = (
                favorite == "home"
                and margin == 1
                or favorite == "away"
                and margin == -1
            )
            if favorite_one_goal:
                row["probability"] *= 1 + delta


def score_matrix(
    home_xg: float,
    away_xg: float,
    max_goals: int = 8,
    mode: str = "baseline",
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    open_profile = (context or {}).get("open_game_profile") or {}
    open_effect = clamp(float(open_profile.get("score", 0)) / 5, 0, 1)
    variance = (context or {}).get("variance_profile") or {}
    overdispersion = float(variance.get("overdispersion", 0) or 0)
    favorite = open_profile.get("favorite_side")
    rows = []
    for h in range(max_goals + 1):
        for a in range(max_goals + 1):
            poisson_probability = poisson(h, home_xg) * poisson(a, away_xg)
            if overdispersion > 0:
                nb_probability = negative_binomial(h, home_xg, overdispersion) * negative_binomial(a, away_xg, overdispersion)
                mix = clamp(overdispersion * 1.45, 0, 0.42)
                probability = poisson_probability * (1 - mix) + nb_probability * mix
            else:
                probability = poisson_probability
            probability *= dixon_coles_multiplier(h, a, home_xg, away_xg, mode)
            total_goals = h + a
            if mode == "conservative":
                if h == a and total_goals <= 2:
                    probability *= 1.22
                if total_goals <= 1:
                    probability *= 1.12
            elif mode == "upset":
                if f"{h}-{a}" in {"0-0", "1-1", "0-1", "1-0", "1-2", "2-1"}:
                    probability *= 1.16
                if total_goals <= 2:
                    probability *= 1.08
            elif mode == "open":
                if total_goals >= 3:
                    probability *= 1.15
                if h != a:
                    probability *= 1.08
            if open_effect > 0:
                favorite_wins = (
                    (favorite == "home" and h > a)
                    or (favorite == "away" and a > h)
                )
                if total_goals >= 3:
                    probability *= 1 + 0.10 * open_effect
                if total_goals >= 4:
                    probability *= 1 + 0.16 * open_effect
                if favorite_wins and total_goals >= 4 and h > 0 and a > 0:
                    probability *= 1 + 0.20 * open_effect
            rows.append(
                {
                    "home_goals": h,
                    "away_goals": a,
                    "score": f"{h}-{a}",
                    "probability": probability,
                }
            )
    apply_goal_distribution_adjustments(rows, context)
    total = sum(r["probability"] for r in rows)
    for row in rows:
        row["probability"] = row["probability"] / total if total else 0
    return rows


def scoreline_meta(score: str, probability: float | None = None) -> dict[str, Any]:
    if "其它" in score:
        return {
            "score_group": "其它比分",
            "score_priority": 0,
            "score_note": "范围太宽，只能当冷门观察，不能当主比分",
        }
    clean = score.replace(":", "-")
    try:
        home_goals, away_goals = [int(part) for part in clean.split("-", 1)]
    except ValueError:
        return {
            "score_group": "未知比分",
            "score_priority": 0,
            "score_note": "比分格式无法识别，只作观察",
        }

    total_goals = home_goals + away_goals
    margin = abs(home_goals - away_goals)
    common_scores = {"0-0", "1-0", "0-1", "1-1", "2-0", "0-2", "2-1", "1-2", "2-2"}
    expanded_scores = {"3-0", "0-3", "3-1", "1-3", "3-2", "2-3"}

    if clean in common_scores:
        return {
            "score_group": "常见比分",
            "score_priority": 3,
            "score_note": "和胜平负、总进球主线一致，可作为比分参考",
        }
    if clean in expanded_scores or (total_goals <= 4 and margin <= 2):
        return {
            "score_group": "扩大比分",
            "score_priority": 2,
            "score_note": "需要比赛节奏打开，适合小额防线观察",
        }
    return {
        "score_group": "冷门比分",
        "score_priority": 1,
        "score_note": "命中率低，不能作为核心推荐",
    }


def ranked_scorelines(
    matrix: list[dict[str, Any]],
    limit: int = 8,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> tuple[float, float, float, float]:
        meta = scoreline_meta(row["score"], row["probability"])
        total_goals = row["home_goals"] + row["away_goals"]
        margin = abs(row["home_goals"] - row["away_goals"])
        deep_favorite = bool(context and context.get("deep_favorite_profile"))
        favorite = context.get("favorite_side") if context else None
        open_profile = (context or {}).get("open_game_profile") or {}
        stall_profile = (context or {}).get("favorite_stall_profile") or {}
        stall_effect = clamp(float(stall_profile.get("score", 0) or 0), 0, 1)
        open_effect = clamp(float(open_profile.get("score", 0)) / 5, 0, 1)
        if deep_favorite:
            shape_penalty = 0.006 * max(0, total_goals - 5) + 0.003 * max(0, margin - 4)
            if stall_effect >= 0.45 and margin >= 3:
                shape_penalty += 0.016 + stall_effect * 0.020
            elif favorite == "home" and row["home_goals"] > row["away_goals"] and margin >= 3:
                shape_penalty -= 0.025
            elif favorite == "away" and row["away_goals"] > row["home_goals"] and margin >= 3:
                shape_penalty -= 0.025
        else:
            shape_penalty = 0.012 * max(0, total_goals - 3) + 0.010 * max(0, margin - 2)
            if open_effect > 0:
                shape_penalty *= 1 - 0.45 * open_effect
                favorite_wins = (
                    favorite == "home"
                    and row["home_goals"] > row["away_goals"]
                    or favorite == "away"
                    and row["away_goals"] > row["home_goals"]
                )
                if favorite_wins and total_goals >= 4 and row["home_goals"] > 0 and row["away_goals"] > 0:
                    shape_penalty -= 0.015 * open_effect
        priority = meta["score_priority"]
        if stall_effect >= 0.45 and row["score"] in {"0-0", "1-1", "1-0", "0-1", "2-0", "0-2"}:
            priority = max(priority, 3.5)
        elif deep_favorite and total_goals >= 3 and margin >= 3:
            priority = max(priority, 3.4)
        elif open_effect > 0 and total_goals >= 3 and margin <= 3:
            favorite_wins = (
                favorite == "home"
                and row["home_goals"] > row["away_goals"]
                or favorite == "away"
                and row["away_goals"] > row["home_goals"]
            )
            if favorite_wins or (row["home_goals"] == row["away_goals"] and total_goals >= 4):
                priority = max(priority, 2.7 + 0.4 * open_effect)
        return (
            priority,
            row["probability"] - shape_penalty,
            -total_goals,
            -margin,
        )

    rows = sorted(matrix, key=sort_key, reverse=True)[:limit]
    output = []
    for row in rows:
        meta = scoreline_meta(row["score"], row["probability"])
        total_goals = row["home_goals"] + row["away_goals"]
        margin = abs(row["home_goals"] - row["away_goals"])
        stall_effect = clamp(float(((context or {}).get("favorite_stall_profile") or {}).get("score", 0) or 0), 0, 1)
        if context and context.get("deep_favorite_profile") and total_goals >= 3 and margin >= 3 and stall_effect >= 0.45:
            meta = {
                "score_group": "深盘大胜降温",
                "score_priority": 1,
                "score_note": "热门过热且有小比分触发，只能当尾部防线，不能当主比分",
            }
        elif context and context.get("deep_favorite_profile") and total_goals >= 3 and margin >= 3:
            meta = {
                "score_group": "深盘大胜比分",
                "score_priority": 3,
                "score_note": "和深盘让胜方向一致，适合小额比分池，不宜作为主仓单压",
            }
        output.append(
            {
                "score": row["score"],
                "probability": row["probability"],
                **meta,
            }
        )
    return output


def score_grid(matrix: list[dict[str, Any]], max_goals: int = 4) -> list[dict[str, Any]]:
    return [
        {
            "score": row["score"],
            "probability": row["probability"],
        }
        for row in matrix
        if row["home_goals"] <= max_goals and row["away_goals"] <= max_goals
    ]


def handicap_result_for_score(row: dict[str, Any], handicap: int | None) -> str | None:
    if handicap is None:
        return None
    if "home_goals" in row and "away_goals" in row:
        home_goals = int(row["home_goals"])
        away_goals = int(row["away_goals"])
    else:
        parts = str(row.get("score", "")).replace(":", "-").split("-")
        if len(parts) != 2:
            return None
        try:
            home_goals = int(parts[0])
            away_goals = int(parts[1])
        except ValueError:
            return None
    diff = home_goals + int(handicap) - away_goals
    if diff > 0:
        return "让胜"
    if diff == 0:
        return "让平"
    return "让负"


def handicap_scoreline_lean(top_scores: list[dict[str, Any]], handicap: int | None) -> dict[str, Any] | None:
    if handicap is None:
        return None
    buckets = {"让胜": 0.0, "让平": 0.0, "让负": 0.0}
    for index, row in enumerate(top_scores):
        selection = handicap_result_for_score(row, handicap)
        if not selection:
            continue
        # 概率相近时仍然让前排比分有更高解释权，避免高赔项反向覆盖主叙事。
        rank_weight = 1.0 / (index + 1)
        buckets[selection] += float(row.get("probability") or 0) + rank_weight * 0.015
    total = sum(buckets.values())
    if total <= 0:
        return None
    selection, weight = max(buckets.items(), key=lambda item: item[1])
    return {
        "selection": selection,
        "share": round(weight / total, 4),
        "buckets": {key: round(value / total, 4) for key, value in buckets.items()},
    }


def recommendation_context(
    match: dict[str, Any],
    model_probs: dict[str, float],
    xg: dict[str, float],
    matrix: list[dict[str, Any]],
    handicap: int | None,
) -> dict[str, Any]:
    elo_gap = abs(float(match.get("home_elo", 1800)) - float(match.get("away_elo", 1800)))
    prob_gap = abs(model_probs["home"] - model_probs["away"])
    balanced = (
        elo_gap <= 180
        and prob_gap <= 0.22
        and model_probs["draw"] >= 0.24
        and 0.75 <= xg["home"] <= 1.90
        and 0.75 <= xg["away"] <= 1.90
    )
    favorite_side = "home" if model_probs["home"] >= model_probs["away"] else "away"
    xg_gap = abs(float(xg["home"]) - float(xg["away"]))
    deep_favorite_profile = (
        handicap is not None
        and abs(handicap) >= 2
        and (
            elo_gap >= 300
            or prob_gap >= 0.50
            or xg_gap >= 1.75
        )
    )
    stall_profile = favorite_stall_profile(match, model_probs, xg, handicap)
    draw_protection_required = float(stall_profile.get("score", 0) or 0) >= 0.45
    context_seed = {
        "deep_favorite_profile": deep_favorite_profile,
        "favorite_side": favorite_side,
        "favorite_stall_profile": stall_profile,
        "draw_protection_required": draw_protection_required,
    }
    open_profile = open_game_profile(match, model_probs, xg)
    context_seed["open_game_profile"] = open_profile
    top_scores = ranked_scorelines(matrix, limit=6, context=context_seed)
    scoreline_lean = handicap_scoreline_lean(top_scores, handicap)
    matrix_handicap_probs = rqspf_probs(matrix, handicap) if handicap is not None else None
    matrix_lean = max(matrix_handicap_probs.items(), key=lambda item: item[1])[0] if matrix_handicap_probs else None
    top_score_set = {row["score"] for row in top_scores[:4]}
    one_goal_core = bool({"0-1", "1-0"} & top_score_set)
    low_draw_core = bool({"0-0", "1-1"} & top_score_set)
    return {
        "elo_gap": round(elo_gap, 1),
        "prob_gap": round(prob_gap, 4),
        "balanced_matchup": balanced,
        "score_betting_allowed": balanced or (model_probs["draw"] >= 0.27 and low_draw_core) or draw_protection_required,
        "one_goal_core": one_goal_core,
        "low_draw_core": low_draw_core,
        "draw_protection_required": draw_protection_required,
        "favorite_stall_profile": stall_profile,
        "favorite_cover_cooldown": round(clamp(float(stall_profile.get("score", 0) or 0) * 0.18, 0, 0.18), 3),
        "handicap_one_goal_mapping": handicap is not None and abs(handicap) == 1 and one_goal_core,
        "deep_favorite_profile": deep_favorite_profile,
        "favorite_side": favorite_side,
        "open_game_profile": open_profile,
        "xg_gap": round(xg_gap, 3),
        "top_score_set": sorted(top_score_set),
        "handicap_matrix_probs": {key: round(value, 4) for key, value in matrix_handicap_probs.items()} if matrix_handicap_probs else None,
        "handicap_matrix_lean": matrix_lean,
        "handicap_scoreline_lean": scoreline_lean,
    }


def apply_recommendation_rules(options: list[dict[str, Any]], context: dict[str, Any], handicap: int | None) -> list[dict[str, Any]]:
    stall_profile = context.get("favorite_stall_profile") or {}
    stall_score = float(stall_profile.get("score", 0) or 0)
    draw_protection_required = bool(context.get("draw_protection_required")) or stall_score >= 0.45
    for item in options:
        play_type = item.get("play_type")
        selection = item.get("selection")
        notes = list(item.get("rule_notes", []))

        if play_type == "比分":
            if context.get("deep_favorite_profile"):
                high_favorite_score = (
                    selection in {"4:0", "5:0", "4:1", "5:1", "胜其它"}
                    if context.get("favorite_side") == "home"
                    else selection in {"0:4", "0:5", "1:4", "1:5", "负其它"}
                )
                if high_favorite_score:
                    notes.append("深盘强弱悬殊场，需给大胜尾部留保护")
                    item["tail_hedge"] = True
                    item["recommendation_role"] = "favorite_tail_hedge"
                    item["risk_score"] = max(75, int(item.get("risk_score") or 75))
                    item["risk_level"] = risk_level(item["risk_score"])
                    if stall_score >= 0.45:
                        notes.append("热门过热且有小比分触发，大胜比分降为尾部保护")
                        item["risk_score"] = max(86, int(item.get("risk_score") or 86))
                        item["risk_level"] = risk_level(item["risk_score"])
                        item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) - 0.25, 4)
                        if item.get("decision") == "可小注":
                            item["decision"] = "高风险观察"
                            item["reason"] = "热门降温触发，大胜比分只能小额防尾部"
                    if item.get("decision") in {"放弃", "高风险观察"} and item.get("sp"):
                        item["decision"] = "高风险观察"
                        item["reason"] = "深盘强队存在大胜尾部，只能小额保护"
                    item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.10, 4)
            if draw_protection_required and selection in {"0:0", "1:1", "1:0", "0:1"}:
                notes.append("热门降温/低比分触发，可作为平局或一球小胜保护")
                item["recommendation_role"] = "draw_low_score_protection"
                item["score_bet_allowed"] = True
                item["risk_score"] = max(62, int(item.get("risk_score") or 62))
                item["risk_level"] = risk_level(item["risk_score"])
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.12, 4)
                if item.get("sp") and item.get("decision") == "放弃":
                    item["decision"] = "观察"
                    item["reason"] = "热门降温触发，低比分只做保护观察"
            if context["score_betting_allowed"] and item.get("score_priority") == 3 and (item.get("model_prob") or 0) >= 0.055:
                notes.append("实力接近/平局空间足，比分可小额参考")
                item["score_bet_allowed"] = True
                item["risk_score"] = max(55, int(item.get("risk_score") or 70))
                item["risk_level"] = risk_level(item["risk_score"])
                if item.get("sp") and item.get("ev") is not None and item["ev"] >= -0.08 and item.get("decision") == "放弃":
                    item["decision"] = "观察"
                    item["reason"] = "实力接近场，比分赔率接近模型线，可小额观察"
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.16, 4)
            else:
                item["score_bet_allowed"] = bool(item.get("score_bet_allowed"))

        if play_type == "让球胜平负" and context["handicap_one_goal_mapping"]:
            if handicap == 1 and selection == "让平":
                notes.append("受让1且主比分含0:1，优先防让平")
                item["mapping_priority"] = 3
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.22, 4)
                if item.get("decision") == "放弃" and item.get("sp"):
                    item["decision"] = "观察"
                    item["reason"] = "主比分落在一球小负区间，受让1需防让平"
            elif handicap == 1 and selection == "让胜":
                notes.append("受让1方向成立，但一球小负会落到让平")
                item["mapping_priority"] = 2
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) - 0.06, 4)
            elif handicap == -1 and selection == "让平":
                notes.append("让1且主比分含1:0，优先防让平")
                item["mapping_priority"] = 3
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.22, 4)
                if item.get("decision") == "放弃" and item.get("sp"):
                    item["decision"] = "观察"
                    item["reason"] = "主比分落在一球小胜区间，让1需防让平"
            elif handicap == -1 and selection == "让负":
                notes.append("让1方向防强队不穿盘")
                item["mapping_priority"] = 2

        if play_type == "让球胜平负" and context.get("handicap_scoreline_lean"):
            scoreline_lean = context["handicap_scoreline_lean"]
            lean_selection = scoreline_lean.get("selection")
            lean_share = float(scoreline_lean.get("share") or 0)
            if lean_selection and selection != lean_selection and lean_share >= 0.42:
                notes.append(f"与比分主线{lean_selection}不一致，只能作防穿盘/反主线价值观察")
                item["recommendation_role"] = "anti_scoreline_value"
                item["mapping_priority"] = min(int(item.get("mapping_priority") or 0), 1)
                item["risk_score"] = min(100, max(58, int(item.get("risk_score") or 50) + 10))
                item["risk_level"] = risk_level(item["risk_score"])
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) - 0.35, 4)
                item["stake_pct"] = round(min(float(item.get("stake_pct") or 0), 0.002), 4)
                if item.get("decision") == "可小注":
                    item["decision"] = "观察"
                    item["reason"] = "让球选择与比分主线冲突，只能防穿盘观察"
                elif item.get("decision") == "观察":
                    item["reason"] = "反比分主线的赔率价值，只适合小额防线"
            elif lean_selection and selection == lean_selection:
                notes.append("让球选择与比分主线一致")
                item["recommendation_role"] = "main_scoreline_aligned"
                item["mapping_priority"] = max(int(item.get("mapping_priority") or 0), 2)
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.12, 4)

        if play_type == "总进球" and context.get("deep_favorite_profile") and selection in {"5", "6", "7+"}:
            notes.append("深盘强弱悬殊场，总进球高位需作为尾部风险")
            item["tail_hedge"] = True
            item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.08, 4)
            if item.get("decision") == "放弃" and item.get("sp"):
                item["decision"] = "观察"
                item["reason"] = "深盘场大胜尾部保护，只适合小额"
        elif play_type == "总进球" and context.get("deep_favorite_profile") and selection in {"0", "1", "2"}:
            if draw_protection_required:
                notes.append("热门降温触发，低总进球可作小额保护")
                item["recommendation_role"] = "low_total_protection"
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.08, 4)
                item["risk_score"] = max(64, int(item.get("risk_score") or 64))
                item["risk_level"] = risk_level(item["risk_score"])
                if item.get("decision") == "放弃" and item.get("sp"):
                    item["decision"] = "观察"
                    item["reason"] = "热门降温触发，低总进球只做保护"
            else:
                notes.append("深盘强弱悬殊场，低总进球高赔不能进入核心推荐")
                item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) - 0.22, 4)
                item["risk_score"] = max(70, int(item.get("risk_score") or 70))
                item["risk_level"] = risk_level(item["risk_score"])
                if item.get("decision") == "可小注":
                    item["decision"] = "观察"
                    item["reason"] = "深盘场低进球高赔陷阱，只能观察"

        if notes:
            item["rule_notes"] = notes
    return options


def actionability_score(item: dict[str, Any]) -> tuple[float, str, str]:
    decision = str(item.get("decision") or "")
    play_type = str(item.get("play_type") or "")
    ev = float(item.get("ev") if item.get("ev") is not None else -0.25)
    probability = float(item.get("model_prob") or 0)
    risk = int(item.get("risk_score") or 100)
    role = str(item.get("recommendation_role") or "")

    score = {
        "可小注": 68,
        "观察": 44,
        "高风险观察": 26,
        "放弃": -25,
        "不可用": -90,
    }.get(decision, 0)
    score += clamp(ev, -0.25, 0.45) * 120
    score += min(probability, 0.65) * 28
    score -= risk * 0.34
    score += int(item.get("mapping_priority") or 0) * 6
    score += float(item.get("risk_adjusted_score") or 0) * 10

    score += {
        "胜平负": 12,
        "让球胜平负": 9,
        "总进球": 6,
        "比分": -12,
        "半全场": -18,
    }.get(play_type, 0)

    if item.get("score_bet_allowed"):
        score += 5
    if role == "main_scoreline_aligned":
        score += 8
    elif role == "anti_scoreline_value":
        score -= 18
    elif role in {"draw_low_score_protection", "low_total_protection"}:
        score -= 2
    elif role == "favorite_tail_hedge":
        score -= 10

    if ev <= 0:
        score -= 30
    if risk >= 82:
        score -= 24
    elif risk >= 72:
        score -= 12
    if play_type in {"比分", "半全场"} and probability < 0.055:
        score -= 16

    if decision == "不可用" or item.get("sp") is None:
        return round(score, 2), "不可下单", "体彩未开售或缺少SP"
    if decision == "放弃" or ev <= 0:
        return round(score, 2), "放弃", "价格不划算或风险收益不匹配"
    if decision != "可小注":
        if role in {"draw_low_score_protection", "low_total_protection", "favorite_tail_hedge", "anti_scoreline_value"} or play_type in {"比分", "半全场"}:
            return round(score, 2), "防冷小注", "只适合小金额覆盖，不作为主仓"
        if score >= 32 and risk <= 78:
            return round(score, 2), "可搭配", "有参考价值，但未达到主推门槛"
        return round(score, 2), "观察", "方向或价格有参考，但不作为主推"
    if score >= 50 and risk <= 70 and play_type not in {"比分", "半全场"}:
        return round(score, 2), "主推", "价值、风险和玩法稳定性较均衡"
    if score >= 32 and risk <= 78:
        return round(score, 2), "可搭配", "可作为方案搭配，金额不宜过高"
    if role in {"draw_low_score_protection", "low_total_protection", "favorite_tail_hedge", "anti_scoreline_value"} or play_type in {"比分", "半全场"}:
        return round(score, 2), "防冷小注", "只适合小金额覆盖，不作为主仓"
    return round(score, 2), "观察", "需要临场SP、阵容或风险再确认"


def apply_actionability_scores(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in options:
        score, tier, reason = actionability_score(item)
        item["action_score"] = score
        item["action_tier"] = tier
        item["action_reason"] = reason
        if tier in {"放弃", "不可下单"}:
            item["stake_pct"] = 0.0
        elif tier == "观察":
            item["stake_pct"] = 0.0
        elif tier == "防冷小注":
            item["stake_pct"] = round(min(float(item.get("stake_pct") or 0.0), 0.002), 4)
        elif tier == "可搭配":
            item["stake_pct"] = round(min(float(item.get("stake_pct") or 0.0), 0.006), 4)
    return options


def captured_at_key(row: dict[str, Any]) -> str:
    return str(row.get("captured_at") or row.get("updated_at") or row.get("timestamp") or "")


def derive_market_signal(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history:
        return {"direction": "无赔率数据", "strength": 0, "latest_probs": None, "movement": {}, "bookmakers": 0, "snapshots": 0, "weight": 0.0}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(history, key=captured_at_key):
        if row["market"] == "h2h":
            grouped[row["bookmaker"]].append(row)

    latest_by_book: list[dict[str, float]] = []
    first_by_book: list[dict[str, float]] = []
    for rows in grouped.values():
        by_time: dict[str, dict[str, float]] = defaultdict(dict)
        for row in rows:
            by_time[captured_at_key(row)][row["selection"]] = float(row["odds_decimal"])
        complete = [(ts, odds) for ts, odds in by_time.items() if {"home", "draw", "away"} <= set(odds)]
        if complete:
            first_by_book.append(complete[0][1])
            latest_by_book.append(complete[-1][1])

    if not latest_by_book:
        return {"direction": "无完整胜平负赔率", "strength": 0, "latest_probs": None, "movement": {}, "bookmakers": 0, "snapshots": 0, "weight": 0.0}

    def avg_probs(samples: list[dict[str, float]]) -> dict[str, float]:
        acc = {"home": 0.0, "draw": 0.0, "away": 0.0}
        valid = 0
        for sample in samples:
            probs = implied_probabilities(sample)
            if probs:
                valid += 1
                for key in acc:
                    acc[key] += probs[key]
        return {k: acc[k] / valid for k in acc} if valid else acc

    first = avg_probs(first_by_book)
    latest = avg_probs(latest_by_book)
    movement = {k: latest[k] - first.get(k, latest[k]) for k in latest}
    leader = max(movement, key=lambda k: abs(movement[k]))
    direction_name = {"home": "主胜", "draw": "平局", "away": "客胜"}[leader]
    strength = abs(movement[leader])
    if strength < 0.015:
        direction = "市场基本稳定"
    else:
        direction = f"{direction_name}方向增强" if movement[leader] > 0 else f"{direction_name}方向降温"
    snapshot_count = len({captured_at_key(row) for row in history if row.get("market") == "h2h" and captured_at_key(row)})
    bookmaker_count = len(latest_by_book)
    weight = dynamic_market_weight(bookmaker_count, snapshot_count, strength)
    return {
        "direction": direction,
        "strength": strength,
        "latest_probs": latest,
        "movement": movement,
        "bookmakers": bookmaker_count,
        "snapshots": snapshot_count,
        "weight": weight,
    }


def dynamic_market_weight(bookmakers: int, snapshots: int, movement_strength: float) -> float:
    if bookmakers <= 0:
        return 0.0
    weight = 0.22
    weight += min(bookmakers, 5) * 0.035
    weight += min(snapshots, 6) * 0.018
    if movement_strength >= 0.08:
        weight += 0.08
    elif movement_strength >= 0.04:
        weight += 0.05
    elif movement_strength >= 0.02:
        weight += 0.025
    return round(clamp(weight, 0.18, 0.58), 3)


def upset_profile(match: dict[str, Any]) -> dict[str, Any]:
    triggers = match.get("upset_triggers", {})
    active = []
    for key, rule in UPSET_RULES.items():
        label, base_weight = rule
        value = triggers.get(key, False)
        confidence = 1.0
        if isinstance(value, dict):
            enabled = bool(value.get("enabled", True))
            strength = float(value.get("strength", 1.0))
            confidence = float(value.get("confidence", 1.0))
            weight = base_weight * strength * confidence
        elif isinstance(value, (int, float)):
            enabled = value > 0
            weight = base_weight * float(value)
        else:
            enabled = bool(value)
            weight = base_weight if enabled else 0.0
        if enabled:
            active.append({"key": key, "label": label, "weight": round(weight, 2), "confidence": confidence})
    score = sum(item["weight"] for item in active)
    if score <= 3:
        level = "低"
        adjustment = {"home": -0.015, "draw": 0.008, "away": 0.007}
    elif score <= 6:
        level = "中低"
        adjustment = {"home": -0.045, "draw": 0.027, "away": 0.018}
    elif score <= 9:
        level = "中高"
        adjustment = {"home": -0.09, "draw": 0.052, "away": 0.038}
    else:
        level = "高"
        adjustment = {"home": -0.145, "draw": 0.075, "away": 0.07}
    return {"score": round(score, 2), "level": level, "active": active, "adjustment": adjustment}


def apply_adjustment(probs: dict[str, float], adjustment: dict[str, float], favorite: str) -> dict[str, float]:
    mapped = dict(probs)
    underdog = "away" if favorite == "home" else "home"
    mapped[favorite] += adjustment["home"]
    mapped["draw"] += adjustment["draw"]
    mapped[underdog] += adjustment["away"]
    return normalize_probs(mapped)


def total_goals_summary(matrix: list[dict[str, Any]]) -> dict[str, Any]:
    bins: dict[str, float] = defaultdict(float)
    exact: dict[str, float] = defaultdict(float)
    for row in matrix:
        total_goals = row["home_goals"] + row["away_goals"]
        exact_key = "7+" if total_goals >= 7 else str(total_goals)
        exact[exact_key] += row["probability"]
        if total_goals <= 1:
            bins["0-1"] += row["probability"]
        elif total_goals <= 3:
            bins["2-3"] += row["probability"]
        else:
            bins["4+"] += row["probability"]
    most_likely = max(exact, key=exact.get) if exact else "-"
    best_range = max(bins, key=bins.get) if bins else "-"
    return {
        "exact": [{"goals": key, "probability": round(exact.get(key, 0), 4)} for key in ["0", "1", "2", "3", "4", "5", "6", "7+"]],
        "ranges": [{"range": key, "probability": round(bins.get(key, 0), 4)} for key in ["0-1", "2-3", "4+"]],
        "most_likely": most_likely,
        "best_range": best_range,
        "low_score_risk": level_from_probability(bins.get("0-1", 0)),
        "high_score_risk": level_from_probability(bins.get("4+", 0)),
    }


def authority_side_strength_score(match: dict[str, Any]) -> float:
    configured = match.get("authority_side_strength")
    if isinstance(configured, (int, float)):
        return clamp(float(configured), -2, 2)
    if isinstance(configured, dict):
        if "score" in configured:
            return clamp(float(configured["score"]), -2, 2)
        home_total = 0.0
        away_total = 0.0
        weight_total = 0.0
        for source in configured.get("sources", []):
            source_id = str(source.get("source_id", "")).lower()
            weight = float(source.get("weight", AUTHORITY_SOURCE_WEIGHTS.get(source_id, 0.45)))
            confidence = float(source.get("confidence", 1.0))
            home_score = float(source.get("home_score", 0.0))
            away_score = float(source.get("away_score", 0.0))
            applied_weight = weight * confidence
            home_total += home_score * applied_weight
            away_total += away_score * applied_weight
            weight_total += applied_weight
        if weight_total > 0:
            return clamp((home_total - away_total) / weight_total, -2, 2)
    return 0.0


def fifa_rank_value(match: dict[str, Any], side: str) -> float | None:
    data = match.get("fifa_ranking") or match.get("fifa_rank")
    if isinstance(data, dict):
        value = data.get(side) or data.get(f"{side}_rank")
        if value is not None:
            return float(value)
    key = "home_fifa_rank" if side == "home" else "away_fifa_rank"
    if match.get(key) is not None:
        return float(match[key])
    return None


def fifa_ranking_score(match: dict[str, Any]) -> float:
    configured = match.get("fifa_ranking_strength")
    if isinstance(configured, (int, float)):
        return clamp(float(configured), -2, 2)
    home_rank = fifa_rank_value(match, "home")
    away_rank = fifa_rank_value(match, "away")
    if home_rank is None or away_rank is None or home_rank <= 0 or away_rank <= 0:
        return 0.0
    confidence = 1.0
    data = match.get("fifa_ranking") or match.get("fifa_rank")
    if isinstance(data, dict):
        confidence = float(data.get("confidence", confidence))
    # Lower rank is stronger. Use a log ratio so rank 2 vs 70 matters,
    # while rank 8 vs 20 does not overwhelm market and Elo.
    ratio_score = math.log(away_rank / home_rank) / math.log(4)
    gap_score = (away_rank - home_rank) / 55
    return clamp((ratio_score * 0.62 + gap_score * 0.38) * confidence, -2, 2)


def formal_component_score(data: dict[str, Any], component: str) -> float:
    if not isinstance(data, dict):
        return 0.0
    value = data.get(component)
    if isinstance(value, (int, float)):
        return clamp(float(value), -2, 2)
    if not isinstance(value, dict):
        return 0.0

    score = 0.0
    if "score" in value:
        score += float(value["score"])
    if "points_per_game" in value:
        score += (float(value["points_per_game"]) - 1.55) * 0.70
    if "goal_diff_per_game" in value:
        score += float(value["goal_diff_per_game"]) * 0.38
    if "opponent_strength" in value:
        score += float(value["opponent_strength"]) * 0.45
    if "away_points_per_game" in value:
        score += (float(value["away_points_per_game"]) - 1.25) * 0.35
    if value.get("qualified_direct"):
        score += 0.28
    if "stage" in value:
        score += FORMAL_STAGE_BONUS.get(str(value["stage"]).lower(), 0.0)
    if "sample_size" in value:
        sample = clamp(float(value["sample_size"]) / 10, 0.45, 1.0)
        score *= sample
    return clamp(score, -2, 2)


def formal_side_score(data: Any) -> float:
    if isinstance(data, (int, float)):
        return clamp(float(data), -2.5, 2.5)
    if not isinstance(data, dict):
        return 0.0
    if "score" in data:
        return clamp(float(data["score"]), -2.5, 2.5)

    qualifier = formal_component_score(data, "qualifiers")
    continental = formal_component_score(data, "continental")
    recent = formal_component_score(data, "recent_official")
    cross = formal_component_score(data, "cross_confed")
    confed = CONFEDERATION_BASE_STRENGTH.get(str(data.get("confederation", "")).upper(), 0.0)
    score = qualifier * 0.38 + continental * 0.27 + recent * 0.22 + cross * 0.08 + confed * 0.05
    return clamp(score, -2.5, 2.5)


def formal_competition_strength_score(match: dict[str, Any]) -> float:
    configured = match.get("formal_competition_strength")
    if isinstance(configured, (int, float)):
        return clamp(float(configured), -2.5, 2.5)
    if isinstance(configured, dict):
        if "score" in configured:
            return clamp(float(configured["score"]), -2.5, 2.5)
        home = formal_side_score(configured.get("home"))
        away = formal_side_score(configured.get("away"))
        confidence = float(configured.get("confidence", 1.0))
        return clamp((home - away) * confidence, -2.5, 2.5)
    return 0.0


def match_process_rating_score(match: dict[str, Any]) -> float:
    configured = match.get("match_process_rating")
    if isinstance(configured, (int, float)):
        return clamp(float(configured), -2, 2)
    stats = match.get("match_process_stats") or match.get("live_match_stats")
    if not isinstance(stats, dict):
        return 0.0

    def side_value(side: str, key: str, default: float = 0.0) -> float:
        data = stats.get(side, {})
        return float(data.get(key, default)) if isinstance(data, dict) else default

    home_shots = side_value("home", "shots")
    away_shots = side_value("away", "shots")
    home_sot = side_value("home", "shots_on_target")
    away_sot = side_value("away", "shots_on_target")
    home_poss = side_value("home", "possession", 50)
    away_poss = side_value("away", "possession", 50)
    home_goals = side_value("home", "goals")
    away_goals = side_value("away", "goals")
    home_cards = side_value("home", "yellow_cards") + side_value("home", "red_cards") * 2.5
    away_cards = side_value("away", "yellow_cards") + side_value("away", "red_cards") * 2.5

    shot_delta = clamp((home_shots - away_shots) / 8, -1.4, 1.4)
    sot_delta = clamp((home_sot - away_sot) / 4, -1.8, 1.8)
    possession_delta = clamp((home_poss - away_poss) / 25, -1.0, 1.0)
    goal_delta = clamp((home_goals - away_goals) / 2, -1.5, 1.5)
    discipline_delta = clamp((away_cards - home_cards) / 4, -0.7, 0.7)
    return clamp(
        sot_delta * 0.34
        + shot_delta * 0.22
        + possession_delta * 0.12
        + goal_delta * 0.22
        + discipline_delta * 0.10,
        -2,
        2,
    )


def over_under_lines(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lines = []
    for line in (1.5, 2.5, 3.5):
        over = sum(row["probability"] for row in matrix if row["home_goals"] + row["away_goals"] > line)
        under = 1 - over
        if line == 1.5:
            lean = "大1.5" if over >= 0.62 else "小1.5" if under >= 0.55 else "观望"
        elif line == 2.5:
            lean = "大2.5" if over >= 0.54 else "小2.5" if under >= 0.56 else "五五开"
        else:
            lean = "小3.5" if under >= 0.70 else "大3.5" if over >= 0.35 else "小3.5轻微"
        lines.append({"line": line, "over": round(over, 4), "under": round(under, 4), "lean": lean})
    return lines


def softmax_market_model(market_probs: dict[str, float], deltas: dict[str, float]) -> dict[str, float]:
    raw = {}
    for key in ("home", "draw", "away"):
        raw[key] = math.log(max(market_probs.get(key, 0), 0.0001)) + float(deltas.get(key, 0))
    denom = sum(math.exp(value) for value in raw.values())
    return {key: math.exp(raw[key]) / denom for key in raw}


def feature_deltas(match: dict[str, Any], market_signal: dict[str, Any], upset: dict[str, Any]) -> dict[str, float]:
    configured = match.get("value_feature_scores", {})
    dimensions = match.get("dimension_scores", {})
    group_context = find_group_context(match)

    def score(name: str, fallback: float = 0.0) -> float:
        return clamp(float(configured.get(name, dimensions.get(name, fallback))), -2, 2)

    strength = score("strength", (float(match.get("home_elo", 1800)) - float(match.get("away_elo", 1800))) / 180)
    fifa_rank = score("fifa_ranking", fifa_ranking_score(match))
    formal = score("formal_competition_strength", formal_competition_strength_score(match))
    process = score("process")
    lineup = score("lineup")
    tactics = score("tactics")
    authority = score("authority_side_strength", authority_side_strength_score(match))
    process_rating = score("match_process_rating", match_process_rating_score(match))
    schedule = score("schedule")
    set_piece_keeper = score("set_piece_keeper")
    motivation_fallback = 0.0
    if group_context:
        home = group_context.get("home") or {}
        away = group_context.get("away") or {}
        motivation_fallback = clamp(
            (float(home.get("points", 0)) - float(away.get("points", 0))) * 0.35
            + (float(home.get("goal_diff", 0)) - float(away.get("goal_diff", 0))) * 0.12,
            -2,
            2,
        )
    motivation = score("motivation", motivation_fallback)
    referee = score("referee")
    tempo = clamp(float(match.get("tempo_score", 0)), -3, 3)
    upset_strength = clamp(float(upset.get("score", 0)) / 5, 0, 2)
    favorite = "home"
    latest = market_signal.get("latest_probs")
    if latest:
        favorite = "home" if latest.get("home", 0) >= latest.get("away", 0) else "away"
    elif float(match.get("home_elo", 1800)) < float(match.get("away_elo", 1800)):
        favorite = "away"

    home_core = (
        strength * 0.040
        + fifa_rank * 0.022
        + formal * 0.034
        + process * 0.030
        + authority * 0.026
        + process_rating * 0.030
        + lineup * 0.040
        + tactics * 0.030
        + schedule * 0.020
        + set_piece_keeper * 0.020
        + motivation * 0.015
        + referee * 0.015
    )
    away_core = -home_core
    if favorite == "home":
        home_core -= upset_strength * 0.040
        away_core += upset_strength * 0.030
    else:
        away_core -= upset_strength * 0.040
        home_core += upset_strength * 0.030

    stall_probs = latest or elo_probabilities(float(match.get("home_elo", 1800)), float(match.get("away_elo", 1800)), match.get("neutral", True))
    stall_xg = estimate_expected_goals(match, stall_probs, "market")
    stall = favorite_stall_profile(match, stall_probs, stall_xg, match.get("sporttery_handicap"))
    stall_score = float(stall.get("score", 0) or 0)
    if stall_score >= 0.45:
        cooldown = min(0.070, 0.034 + stall_score * 0.042)
        if favorite == "home":
            home_core -= cooldown
            away_core += cooldown * 0.25
        else:
            away_core -= cooldown
            home_core += cooldown * 0.25

    balance = clamp(2 - abs(strength), 0, 2)
    low_tempo = clamp(-tempo, 0, 3)
    draw_delta = (
        low_tempo * 0.035
        + balance * 0.030
        + upset_strength * 0.025
        - abs(strength) * 0.020
        - abs(fifa_rank) * 0.008
        - abs(formal) * 0.012
    )
    if stall_score >= 0.45:
        draw_delta += min(0.090, 0.036 + stall_score * 0.060)
        handicap = match.get("sporttery_handicap")
        if handicap is not None and abs(int(handicap)) in {1, 2}:
            draw_delta += 0.012
    return {"home": round(home_core, 4), "draw": round(draw_delta, 4), "away": round(away_core, 4)}


def latest_h2h_odds(history: list[dict[str, Any]], match: dict[str, Any]) -> dict[str, float] | None:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in history:
        if row.get("market") == "h2h" and row.get("selection") in {"home", "draw", "away"}:
            grouped[captured_at_key(row)][row["selection"]].append(float(row["odds_decimal"]))
    if grouped:
        latest_ts = sorted(grouped)[-1]
        latest = grouped[latest_ts]
        if {"home", "draw", "away"} <= set(latest):
            return {key: sum(latest[key]) / len(latest[key]) for key in ("home", "draw", "away")}
    manual = match.get("manual_odds")
    if manual and {"home", "draw", "away"} <= set(manual):
        return {key: float(manual[key]) for key in ("home", "draw", "away")}
    return None


def aicai_market_context(history: list[dict[str, Any]]) -> dict[str, Any]:
    aicai_rows = [row for row in history if str(row.get("source", "")).startswith("aicai_")]
    h2h_rows = [row for row in aicai_rows if row.get("market") == "h2h" and row.get("selection") in {"home", "draw", "away"}]

    def complete_by_time(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, float]]]:
        grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for row in rows:
            grouped[captured_at_key(row)][row["selection"]].append(float(row["odds_decimal"]))
        output = []
        for ts in sorted(grouped):
            sample = grouped[ts]
            if {"home", "draw", "away"} <= set(sample):
                output.append((ts, {key: sum(sample[key]) / len(sample[key]) for key in ("home", "draw", "away")}))
        return output

    europe = None
    series = complete_by_time(h2h_rows)
    if series:
        first_ts, first = series[0]
        latest_ts, latest = series[-1]
        europe = {
            "first_ts": first_ts,
            "latest_ts": latest_ts,
            "first": {key: round(value, 3) for key, value in first.items()},
            "latest": {key: round(value, 3) for key, value in latest.items()},
            "movement": {key: round(latest[key] - first[key], 3) for key in ("home", "draw", "away")},
            "latest_probs": implied_probabilities(latest),
        }

    def line_context(market: str) -> dict[str, Any] | None:
        rows = [row for row in aicai_rows if row.get("market") == market and row.get("selection") == "line"]
        if not rows:
            return None
        rows = sorted(rows, key=captured_at_key)
        first = float(rows[0]["odds_decimal"])
        latest = float(rows[-1]["odds_decimal"])
        return {"first": round(first, 3), "latest": round(latest, 3), "movement": round(latest - first, 3)}

    def latest_value(market: str, selection: str) -> float | None:
        rows = [row for row in aicai_rows if row.get("market") == market and row.get("selection") == selection]
        if not rows:
            return None
        return round(float(sorted(rows, key=captured_at_key)[-1]["odds_decimal"]), 3)

    asia = line_context("aicai_asia_line")
    if asia:
        asia["home_water"] = latest_value("aicai_asia_home_water", "home")
        asia["away_water"] = latest_value("aicai_asia_away_water", "away")
    total = line_context("aicai_total_line")
    if total:
        total["over_water"] = latest_value("aicai_total_over_water", "over")
        total["under_water"] = latest_value("aicai_total_under_water", "under")

    return {
        "source": "aicai_worldcup_stats" if aicai_rows else None,
        "europe": europe,
        "asia": asia,
        "total_goals": total,
        "snapshots": len({captured_at_key(row) for row in aicai_rows if captured_at_key(row)}),
    }


def fair_odds(probability: float) -> float | None:
    return round(1 / probability, 3) if probability > 0 else None


def expected_value(probability: float, odds: float | None) -> float | None:
    return round(probability * odds - 1, 4) if odds and odds > 1 else None


def kelly_fraction(probability: float, odds: float | None) -> float:
    if not odds or odds <= 1:
        return 0.0
    return round(max(0.0, (odds * probability - 1) / (odds - 1)), 4)


def risk_level(score: float) -> str:
    if score <= 30:
        return "低"
    if score <= 45:
        return "中低"
    if score <= 60:
        return "中"
    if score <= 75:
        return "中高"
    return "高"


def play_config(play_type: str) -> dict[str, float]:
    configs = {
        "胜平负": {"threshold": 0.03, "risk_limit": 65, "cap": 0.010},
        "让球胜平负": {"threshold": 0.05, "risk_limit": 70, "cap": 0.008},
        "总进球": {"threshold": 0.06, "risk_limit": 70, "cap": 0.006},
        "比分": {"threshold": 0.10, "risk_limit": 80, "cap": 0.002},
        "半全场": {"threshold": 0.10, "risk_limit": 80, "cap": 0.002},
    }
    return configs.get(play_type, {"threshold": 0.05, "risk_limit": 70, "cap": 0.005})


def option_risk(match: dict[str, Any], play_type: str, model_prob: float, market_prob: float | None, upset: dict[str, Any], market_signal: dict[str, Any]) -> int:
    movement = min(100, float(market_signal.get("strength", 0)) * 900)
    lineup_status = match.get("lineup_status", "unknown")
    lineup = {"confirmed": 10, "minor_issues": 30, "doubtful": 60, "rotating": 80, "unknown": 70}.get(lineup_status, 70)
    upset_risk = min(100, float(upset.get("score", 0)) * 9)
    gap = abs(model_prob - market_prob) if market_prob is not None else 0.08
    gap_risk = min(100, gap * 650)
    play_risk = {"胜平负": 38, "让球胜平负": 48, "总进球": 52, "比分": 76, "半全场": 78}.get(play_type, 50)
    score = movement * 0.20 + lineup * 0.20 + upset_risk * 0.20 + gap_risk * 0.15 + 45 * 0.10 + play_risk * 0.15
    return int(round(clamp(score, 0, 100)))


def decision_for_option(play_type: str, ev: float | None, risk: int, odds: float | None) -> tuple[str, str]:
    if odds is None:
        return "不可用", "缺少体彩SP，不能计算EV"
    if ev is None or ev <= 0:
        return "放弃", "EV≤0"
    config = play_config(play_type)
    if odds < 1.40 and ev < 0.03:
        return "放弃", "低赔无价值"
    if ev < config["threshold"]:
        return "观察", "EV为正但不足玩法门槛"
    if play_type in {"比分", "半全场"} and ev >= 0.30:
        return "高风险观察", "高EV小概率玩法，必须二次核查SP和模型误差"
    if risk > config["risk_limit"]:
        return "高风险观察", "风险分超过玩法上限"
    return "可小注", "EV达到门槛且风险可控"


def latest_sporttery_sp_map(history: list[dict[str, Any]]) -> dict[tuple[str, str], tuple[float, str]]:
    output: dict[tuple[str, str], tuple[float, str]] = {}
    sporttery_markets = {"胜平负", "让球胜平负", "总进球", "比分", "半全场"}
    pool_meta_markets = {"sporttery_pool_open", "sporttery_pool_single", "sporttery_pool_allup"}
    for row in sorted(history, key=captured_at_key):
        if row.get("market") in sporttery_markets:
            output[(row["market"], row["selection"])] = (float(row["odds_decimal"]), row.get("source", "odds_history"))
        elif row.get("market") == "sporttery_handicap" and row.get("selection") == "H":
            output[("__meta__", "handicap")] = (float(row["odds_decimal"]), row.get("source", "odds_history"))
        elif row.get("market") in pool_meta_markets:
            output[(row["market"], str(row["selection"]).upper())] = (float(row["odds_decimal"]), row.get("source", "odds_history"))
    return output


def latest_sporttery_handicap(history: list[dict[str, Any]]) -> int | None:
    handicap = None
    for row in sorted(history, key=captured_at_key):
        if row.get("market") == "sporttery_handicap" and row.get("selection") == "H":
            handicap = int(float(row["odds_decimal"]))
    return handicap


def sporttery_sp(match: dict[str, Any], play_type: str, selection: str, market_sp: dict[tuple[str, str], tuple[float, str]] | None = None) -> tuple[float | None, str | None]:
    if market_sp and (play_type, selection) in market_sp:
        return market_sp[(play_type, selection)]
    data = match.get("sporttery_sp", {})
    if not data:
        return None, None
    buckets = [play_type, play_type.lower(), play_type.replace("胜平负", "spf")]
    for bucket in buckets:
        values = data.get(bucket)
        if isinstance(values, dict) and selection in values:
            return float(values[selection]), "sporttery_sp"
    return None, None


def sporttery_pool_code(play_type: str) -> str | None:
    return {
        "胜平负": "HAD",
        "让球胜平负": "HHAD",
        "比分": "CRS",
        "总进球": "TTG",
        "半全场": "HAFU",
    }.get(play_type)


def sporttery_pool_rules(play_type: str, market_sp: dict[tuple[str, str], tuple[float, str]] | None = None) -> dict[str, Any]:
    code = sporttery_pool_code(play_type)
    if not code or not market_sp:
        default_min_legs = 2 if play_type == "让球胜平负" else 1
        return {"pool_code": code, "is_open": True, "single_allowed": default_min_legs == 1, "min_legs": default_min_legs, "source": None}
    open_row = market_sp.get(("sporttery_pool_open", code))
    single_row = market_sp.get(("sporttery_pool_single", code))
    allup_row = market_sp.get(("sporttery_pool_allup", code))
    is_open = open_row is None or open_row[0] >= 1
    single_allowed = bool(single_row and single_row[0] >= 1)
    allup_allowed = allup_row is None or allup_row[0] >= 1
    min_legs = 1 if single_allowed else 2
    return {
        "pool_code": code,
        "is_open": is_open,
        "single_allowed": single_allowed,
        "allup_allowed": allup_allowed,
        "min_legs": min_legs,
        "source": (single_row or allup_row or open_row or (None, None))[1],
    }


def sporttery_market_probs(
    play_type: str,
    selections: list[str],
    market_sp: dict[tuple[str, str], tuple[float, str]] | None = None,
) -> dict[str, float] | None:
    if not market_sp:
        return None
    implied: dict[str, float] = {}
    for selection in selections:
        row = market_sp.get((play_type, selection))
        if not row or row[0] <= 1:
            return None
        implied[selection] = 1 / float(row[0])
    total = sum(implied.values())
    if total <= 0:
        return None
    return {selection: implied[selection] / total for selection in selections}


def blend_play_probability(
    model_probability: float,
    market_probability: float | None,
    play_type: str,
    handicap: int | None = None,
) -> float:
    if market_probability is None:
        return model_probability
    if play_type == "让球胜平负":
        market_weight = 0.65 if handicap is not None and abs(handicap) >= 2 else 0.42
    elif play_type in {"总进球", "比分"}:
        market_weight = 0.25
    else:
        market_weight = 0.35
    return model_probability * (1 - market_weight) + market_probability * market_weight


def apply_market_conflict_guard(item: dict[str, Any], raw_probability: float | None) -> dict[str, Any]:
    market_prob = item.get("market_prob")
    if raw_probability is None or market_prob is None:
        return item
    gap = raw_probability - market_prob
    item["raw_model_prob"] = round(raw_probability, 4)
    item["market_model_gap"] = round(gap, 4)
    if abs(gap) >= 0.16:
        notes = list(item.get("rule_notes", []))
        notes.append("模型概率与官方SP去水概率分歧较大，降级为观察")
        item["rule_notes"] = notes
        item["risk_score"] = min(100, int(item.get("risk_score") or 50) + 12)
        item["risk_level"] = risk_level(item["risk_score"])
        item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) - 0.18, 4)
        if item.get("decision") == "可小注":
            item["decision"] = "观察"
            item["reason"] = "模型与官方SP分歧大，不能作为核心腿"
    return item


def matrix_1x2(matrix: list[dict[str, Any]]) -> dict[str, float]:
    probs = {"home": 0.0, "draw": 0.0, "away": 0.0}
    for row in matrix:
        if row["home_goals"] > row["away_goals"]:
            probs["home"] += row["probability"]
        elif row["home_goals"] == row["away_goals"]:
            probs["draw"] += row["probability"]
        else:
            probs["away"] += row["probability"]
    return probs


def rqspf_probs(matrix: list[dict[str, Any]], handicap: int) -> dict[str, float]:
    probs = {"让胜": 0.0, "让平": 0.0, "让负": 0.0}
    for row in matrix:
        diff = row["home_goals"] + handicap - row["away_goals"]
        if diff > 0:
            probs["让胜"] += row["probability"]
        elif diff == 0:
            probs["让平"] += row["probability"]
        else:
            probs["让负"] += row["probability"]
    return probs


def sporttery_total_goals(matrix: list[dict[str, Any]]) -> dict[str, float]:
    probs: dict[str, float] = {str(i): 0.0 for i in range(7)}
    probs["7+"] = 0.0
    for row in matrix:
        total = row["home_goals"] + row["away_goals"]
        key = "7+" if total >= 7 else str(total)
        probs[key] += row["probability"]
    return probs


def correct_score_probs(matrix: list[dict[str, Any]], model_probs: dict[str, float]) -> dict[str, float]:
    listed_home = ["1:0", "2:0", "2:1", "3:0", "3:1", "3:2", "4:0", "4:1", "4:2", "5:0", "5:1", "5:2"]
    listed_draw = ["0:0", "1:1", "2:2", "3:3"]
    listed_away = ["0:1", "0:2", "1:2", "0:3", "1:3", "2:3", "0:4", "1:4", "2:4", "0:5", "1:5", "2:5"]
    listed_sets = {
        "home": set(listed_home),
        "draw": set(listed_draw),
        "away": set(listed_away),
    }
    other_labels = {"home": "胜其它", "draw": "平其它", "away": "负其它"}
    ordered = listed_home + ["胜其它"] + listed_draw + ["平其它"] + listed_away + ["负其它"]
    output = {score: 0.0 for score in ordered}
    matrix_totals = {"home": 0.0, "draw": 0.0, "away": 0.0}

    def outcome(home_goals: int, away_goals: int) -> str:
        if home_goals > away_goals:
            return "home"
        if home_goals == away_goals:
            return "draw"
        return "away"

    for row in matrix:
        score = f"{row['home_goals']}:{row['away_goals']}"
        result = outcome(row["home_goals"], row["away_goals"])
        matrix_totals[result] += row["probability"]
        if score in listed_sets[result]:
            output[score] += row["probability"]
        else:
            output[other_labels[result]] += row["probability"]

    # 比分矩阵是主口径，胜平负概率只做温和校准，避免“其它”直接吃掉全部残差。
    calibration_strength = 0.65
    for result, label in other_labels.items():
        base = matrix_totals[result]
        if base <= 0:
            continue
        target = model_probs.get(result, base)
        scale = clamp(1 + (target / base - 1) * calibration_strength, 0.75, 1.25)
        keys = list(listed_sets[result]) + [label]
        for key in keys:
            output[key] *= scale

    total = sum(output.values())
    if total > 0:
        output = {key: value / total for key, value in output.items()}
    return {key: output[key] for key in ordered}


def half_full_probs(home_xg: float, away_xg: float, h1_share: float = 0.45) -> dict[str, float]:
    h1 = score_matrix(home_xg * h1_share, away_xg * h1_share, max_goals=5)
    h2 = score_matrix(home_xg * (1 - h1_share), away_xg * (1 - h1_share), max_goals=5)
    labels = {"home": "胜", "draw": "平", "away": "负"}
    output = {f"{a}{b}": 0.0 for a in labels.values() for b in labels.values()}

    def result(h: int, a: int) -> str:
        if h > a:
            return "home"
        if h == a:
            return "draw"
        return "away"

    for first in h1:
        half_result = labels[result(first["home_goals"], first["away_goals"])]
        for second in h2:
            full_result = labels[result(first["home_goals"] + second["home_goals"], first["away_goals"] + second["away_goals"])]
            output[f"{half_result}{full_result}"] += first["probability"] * second["probability"]
    return output


def evaluate_option(
    match: dict[str, Any],
    play_type: str,
    selection: str,
    probability: float,
    market_prob: float | None,
    upset: dict[str, Any],
    market_signal: dict[str, Any],
    odds_override: float | None = None,
    odds_source: str | None = None,
    market_sp: dict[tuple[str, str], tuple[float, str]] | None = None,
) -> dict[str, Any]:
    sp, source = sporttery_sp(match, play_type, selection, market_sp)
    if odds_override is not None and sp is None:
        sp = odds_override
        source = odds_source or "market_proxy"
    ev = expected_value(probability, sp)
    risk = option_risk(match, play_type, probability, market_prob, upset, market_signal)
    extra: dict[str, Any] = {}
    score_penalty = 0.0
    if play_type == "比分":
        extra = scoreline_meta(selection, probability)
        score_priority = int(extra["score_priority"])
        score_penalty = {0: 0.45, 1: 0.24, 2: 0.08, 3: 0.0}.get(score_priority, 0.2)
        if score_priority <= 0:
            risk = max(risk, 88)
        elif score_priority == 1:
            risk = max(risk, 82)
        elif probability < 0.025:
            risk = max(risk, 78)
        elif probability < 0.06:
            risk = max(risk, 70)
    decision, reason = decision_for_option(play_type, ev, risk, sp)
    if play_type == "比分":
        score_priority = int(extra["score_priority"])
        if score_priority <= 1:
            decision = "高风险观察"
            reason = extra["score_note"]
        elif probability < 0.025:
            decision = "高风险观察"
            reason = "单比分命中率太低，只能小额观察"
        elif decision == "可小注":
            decision = "观察"
            reason = "比分玩法波动高，只作小额参考"
    pool_rules = sporttery_pool_rules(play_type, market_sp)
    if not pool_rules["is_open"]:
        decision = "不可用"
        reason = "官方赛程页显示该玩法未开售"
    kelly = kelly_fraction(probability, sp)
    cap = play_config(play_type)["cap"]
    stake_pct = round(min(kelly * 0.25, cap), 4) if decision in {"可小注", "观察", "高风险观察"} else 0.0
    return {
        "match_id": match["match_id"],
        "play_type": play_type,
        "selection": selection,
        "pool_code": pool_rules["pool_code"],
        "single_allowed": pool_rules["single_allowed"],
        "allup_allowed": pool_rules.get("allup_allowed", True),
        "min_legs": pool_rules["min_legs"],
        "sp": round(sp, 3) if sp else None,
        "sp_source": source,
        "model_prob": round(probability, 4),
        "market_prob": round(market_prob, 4) if market_prob is not None else None,
        "fair_sp": fair_odds(probability),
        "implied_prob": round(1 / sp, 4) if sp else None,
        "value_gap": round(probability - 1 / sp, 4) if sp else None,
        "ev": ev,
        "risk_score": risk,
        "risk_level": risk_level(risk),
        "kelly": kelly,
        "stake_pct": stake_pct,
        "decision": decision,
        "reason": reason,
        "risk_adjusted_score": round((ev or -0.2) - risk * 0.001 - {"比分": 0.18, "半全场": 0.16, "总进球": 0.04}.get(play_type, 0) - score_penalty, 4),
        **extra,
    }


def unavailable_option(
    match: dict[str, Any],
    play_type: str,
    selection: str,
    reason: str,
    market_sp: dict[tuple[str, str], tuple[float, str]] | None = None,
) -> dict[str, Any]:
    sp, source = sporttery_sp(match, play_type, selection, market_sp)
    pool_rules = sporttery_pool_rules(play_type, market_sp)
    return {
        "match_id": match["match_id"],
        "play_type": play_type,
        "selection": selection,
        "pool_code": pool_rules["pool_code"],
        "single_allowed": pool_rules["single_allowed"],
        "allup_allowed": pool_rules.get("allup_allowed", True),
        "min_legs": pool_rules["min_legs"],
        "sp": round(sp, 3) if sp else None,
        "sp_source": source,
        "model_prob": None,
        "market_prob": None,
        "fair_sp": None,
        "implied_prob": round(1 / sp, 4) if sp else None,
        "value_gap": None,
        "ev": None,
        "risk_score": None,
        "risk_level": "不可用",
        "kelly": 0.0,
        "stake_pct": 0.0,
        "decision": "不可用",
        "reason": reason,
        "risk_adjusted_score": -999,
    }


def build_compound_packages(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {(item["play_type"], item["selection"]): item for item in options}
    packages = [
        ("主队不败", [("胜平负", "胜"), ("胜平负", "平")]),
        ("客队不败", [("胜平负", "平"), ("胜平负", "负")]),
        ("分胜负", [("胜平负", "胜"), ("胜平负", "负")]),
        ("总进球低位覆盖", [("总进球", "0"), ("总进球", "1"), ("总进球", "2")]),
        ("总进球中位覆盖", [("总进球", "2"), ("总进球", "3"), ("总进球", "4")]),
    ]
    rows = []
    for name, keys in packages:
        legs = [by_key.get(key) for key in keys]
        if any(item is None or item.get("sp") is None for item in legs):
            rows.append({"name": name, "num_bets": len(keys), "decision": "不可用", "reason": "复选包存在SP缺失"})
            continue
        hit_prob = sum(item["model_prob"] for item in legs)
        package_ev = sum(item["model_prob"] * item["sp"] for item in legs) / len(legs) - 1
        min_return = min(item["sp"] for item in legs)
        max_return = max(item["sp"] for item in legs)
        decision = "放弃" if package_ev <= 0 else "观察" if package_ev < 0.05 else "可小注"
        rows.append(
            {
                "name": name,
                "options": [item["selection"] for item in legs],
                "hit_prob": round(hit_prob, 4),
                "num_bets": len(legs),
                "ev": round(package_ev, 4),
                "min_return_sp": round(min_return, 3),
                "max_return_sp": round(max_return, 3),
                "decision": decision,
                "reason": "复选包EV按注数重算",
            }
        )
    return rows


def build_score_combo_pools(options: list[dict[str, Any]], context: dict[str, Any]) -> list[dict[str, Any]]:
    by_score = {
        item["selection"]: item
        for item in options
        if item.get("play_type") == "比分" and item.get("sp") and item.get("decision") != "不可用"
    }
    home_tail = ["3:0", "4:0", "5:0", "3:1", "4:1", "胜其它"]
    away_tail = ["0:3", "0:4", "0:5", "1:3", "1:4", "负其它"]
    pool_defs = [
        ("低比分池", ["0:0", "1:0", "0:1", "1:1"], "低节奏、平局/一球小胜保护"),
        ("开放比分池", ["2:1", "1:2", "2:2", "3:1", "1:3"], "实力接近但节奏打开的保护"),
        (
            "大胜尾部池",
            home_tail if context.get("favorite_side") == "home" else away_tail,
            "深盘强弱悬殊时只做小额尾部保护",
        ),
    ]
    pools = []
    for name, selections, reason in pool_defs:
        rows = [by_score[selection] for selection in selections if selection in by_score]
        if not rows:
            continue
        hit_prob = sum(float(item.get("model_prob") or 0) for item in rows)
        avg_ev = sum(float(item.get("ev") or -1) for item in rows) / len(rows)
        max_risk = max(int(item.get("risk_score") or 80) for item in rows)
        open_score = float((context.get("open_game_profile") or {}).get("score") or 0)
        stall_score = float((context.get("favorite_stall_profile") or {}).get("score") or 0)
        if context.get("deep_favorite_profile") and name == "低比分池" and stall_score >= 0.45:
            action = "小额保护"
        elif context.get("deep_favorite_profile") and name == "低比分池":
            action = "仅备选"
        elif name == "开放比分池" and open_score >= 3.0 and max_risk < 82:
            action = "可做小复式"
        elif name == "大胜尾部池" and stall_score >= 0.45:
            action = "尾部小防"
        elif name == "大胜尾部池" and not context.get("deep_favorite_profile"):
            action = "仅备选"
        elif max_risk >= 82:
            action = "小额观察"
        elif avg_ev > -0.08:
            action = "可做小复式"
        else:
            action = "不建议"
        pools.append(
            {
                "name": name,
                "selections": [item["selection"] for item in rows],
                "num_options": len(rows),
                "hit_prob": round(hit_prob, 4),
                "avg_ev": round(avg_ev, 4),
                "max_risk": max_risk,
                "action": action,
                "reason": reason,
            }
        )
    return pools


def staking_policy(context: dict[str, Any]) -> dict[str, Any]:
    stall_score = float((context.get("favorite_stall_profile") or {}).get("score") or 0)
    if context.get("deep_favorite_profile"):
        if stall_score >= 0.45:
            score_cap = 0.08
            score_combo_cap = 0.035
            tail_cap = 0.012
            favorite_cover_cap = 0.26
            same_theme_combo_cap = 0.32
        else:
            score_cap = 0.06
            score_combo_cap = 0.03
            tail_cap = 0.02
            favorite_cover_cap = 0.34
            same_theme_combo_cap = 0.40
    elif context.get("balanced_matchup"):
        score_cap = 0.12
        score_combo_cap = 0.06
        tail_cap = 0.0
        favorite_cover_cap = 0.30
        same_theme_combo_cap = 0.36
    else:
        score_cap = 0.08
        score_combo_cap = 0.04
        tail_cap = 0.01
        favorite_cover_cap = 0.32
        same_theme_combo_cap = 0.38
    return {
        "direction_min": 0.70,
        "score_cap": score_cap,
        "score_combo_cap": score_combo_cap,
        "deep_tail_cap": tail_cap,
        "favorite_cover_cap": favorite_cover_cap,
        "same_theme_combo_cap": same_theme_combo_cap,
        "single_score_cap": min(0.04, score_cap / 2),
        "hard_rules": [
            "比分仓不得超过上限",
            "比分串不得高于比分单场仓",
            "深盘尾部保护只允许小额",
            "同一热门穿盘主题不能在多组串关里反复作为主仓",
            "官方SP与模型分歧大的腿不能做核心",
        ],
    }


def build_sporttery_outputs(
    match: dict[str, Any],
    model_probs: dict[str, float],
    matrix: list[dict[str, Any]],
    xg: dict[str, float],
    upset: dict[str, Any],
    market_signal: dict[str, Any],
    h2h_odds: dict[str, float] | None,
    market_sp: dict[tuple[str, str], tuple[float, str]] | None = None,
) -> dict[str, Any]:
    market_probs = market_signal.get("latest_probs") or implied_probabilities(h2h_odds or {}) or None
    sporttery_had_probs = sporttery_market_probs("胜平负", ["胜", "平", "负"], market_sp)
    options: list[dict[str, Any]] = []

    for key, selection in [("home", "胜"), ("draw", "平"), ("away", "负")]:
        odds_proxy = h2h_odds.get(key) if h2h_odds else None
        play_market_prob = (sporttery_had_probs or {}).get(selection) or (market_probs.get(key) if market_probs else None)
        raw_probability = model_probs[key]
        blended_probability = blend_play_probability(raw_probability, play_market_prob, "胜平负")
        item = evaluate_option(
            match,
            "胜平负",
            selection,
            blended_probability,
            play_market_prob,
            upset,
            market_signal,
            odds_override=odds_proxy,
            odds_source="market_h2h_proxy" if odds_proxy else None,
            market_sp=market_sp,
        )
        options.append(apply_market_conflict_guard(item, raw_probability))

    handicap = None
    if match.get("sporttery_handicap") is not None:
        handicap = int(match["sporttery_handicap"])
    elif match.get("handicap") is not None:
        handicap = int(match["handicap"])
    if market_sp and ("__meta__", "handicap") in market_sp:
        handicap = int(market_sp[("__meta__", "handicap")][0])
    if handicap is None:
        for selection in ("让胜", "让平", "让负"):
            options.append(unavailable_option(match, "让球胜平负", selection, "缺少官方让球数H，不能计算让球EV", market_sp))
    else:
        rq_market_probs = sporttery_market_probs("让球胜平负", ["让胜", "让平", "让负"], market_sp)
        for selection, probability in rqspf_probs(matrix, handicap).items():
            market_probability = rq_market_probs.get(selection) if rq_market_probs else None
            blended_probability = blend_play_probability(probability, market_probability, "让球胜平负", handicap)
            item = evaluate_option(match, "让球胜平负", selection, blended_probability, market_probability, upset, market_signal, market_sp=market_sp)
            options.append(apply_market_conflict_guard(item, probability))

    total_goal_selections = [str(i) for i in range(7)] + ["7+"]
    total_goal_market_probs = sporttery_market_probs("总进球", total_goal_selections, market_sp)
    for selection, probability in sporttery_total_goals(matrix).items():
        market_probability = total_goal_market_probs.get(selection) if total_goal_market_probs else None
        blended_probability = blend_play_probability(probability, market_probability, "总进球")
        item = evaluate_option(match, "总进球", selection, blended_probability, market_probability, upset, market_signal, market_sp=market_sp)
        options.append(apply_market_conflict_guard(item, probability))

    score_options = correct_score_probs(matrix, model_probs)
    score_market_probs = sporttery_market_probs("比分", list(score_options.keys()), market_sp)
    for selection, probability in score_options.items():
        market_probability = score_market_probs.get(selection) if score_market_probs else None
        blended_probability = blend_play_probability(probability, market_probability, "比分")
        item = evaluate_option(match, "比分", selection, blended_probability, market_probability, upset, market_signal, market_sp=market_sp)
        options.append(apply_market_conflict_guard(item, probability))

    for selection, probability in half_full_probs(xg["home"], xg["away"]).items():
        options.append(evaluate_option(match, "半全场", selection, probability, None, upset, market_signal, market_sp=market_sp))

    rec_context = recommendation_context(match, model_probs, xg, matrix, handicap)
    leader_key = max(model_probs, key=lambda key: model_probs[key])
    leader_label = {"home": match["home_team"], "draw": "平局", "away": match["away_team"]}[leader_key]
    score_labels = [row["score"] for row in ranked_scorelines(matrix, limit=3, context=rec_context)]
    folk_parallel = folk_parallel_summary_with_context(match, model_probs, leader_label, score_labels)
    options = apply_recommendation_rules(options, rec_context, handicap)
    options = apply_actionability_scores(options)
    play_priority = {"胜平负": 5, "让球胜平负": 4, "总进球": 3, "半全场": 2, "比分": 1}
    ranked = sorted(
        options,
        key=lambda item: (
            {"主推": 5, "可搭配": 4, "防冷小注": 3, "观察": 2, "放弃": 1, "不可下单": 0}.get(item.get("action_tier"), 0),
            item.get("action_score", -100),
            item["decision"] == "可小注",
            item.get("mapping_priority", 0),
            item.get("score_bet_allowed", False),
            play_priority.get(item["play_type"], 0),
            item["risk_adjusted_score"],
            item["model_prob"],
        ),
        reverse=True,
    )
    available = [item for item in ranked if item["decision"] != "不可用"]
    abandoned = [item for item in ranked if item["decision"] in {"放弃", "不可用"}][:20]
    return {
        "settlement": "90分钟含伤停补时，不含加时赛和点球大战",
        "handicap": handicap,
        "value_model": "market_de-vig + feature deltas + softmax",
        "recommendation_context": rec_context,
        "folk_parallel": folk_parallel,
        "options": ranked,
        "score_reference": [
            {
                "score": row["score"],
                "probability": round(row["probability"], 4),
                "score_group": row["score_group"],
                "score_note": row["score_note"],
            }
            for row in ranked_scorelines(matrix, limit=6, context=rec_context)
        ],
        "candidate_pool": [
            item
            for item in available
            if item.get("action_tier") in {"主推", "可搭配", "防冷小注"}
        ][:20],
        "action_summary": {
            "core": [item for item in ranked if item.get("action_tier") == "主推"][:4],
            "support": [item for item in ranked if item.get("action_tier") == "可搭配"][:6],
            "hedge": [item for item in ranked if item.get("action_tier") == "防冷小注"][:6],
        },
        "abandon_list": abandoned,
        "compound_packages": build_compound_packages(ranked),
        "score_combo_pools": build_score_combo_pools(ranked, rec_context),
        "staking_policy": staking_policy(rec_context),
    }


def level_from_probability(value: float) -> str:
    if value >= 0.45:
        return "高"
    if value >= 0.30:
        return "中"
    return "低"


def source_status_from_health(
    source_id: str,
    evidence_count: int,
    health: dict[str, Any],
    enabled: bool = True,
) -> tuple[str, str]:
    if not enabled:
        return "停用", "该源不参与当前抓取"
    if evidence_count > 0:
        return "已拿到", f"本场抓到 {evidence_count} 条可用记录"
    item = health.get(source_id) or {}
    success = int(item.get("success_count") or 0)
    failure = int(item.get("failure_count") or 0)
    last_success = str(item.get("last_success_at") or "")
    last_failure = str(item.get("last_failure_at") or "")
    if success and (not last_failure or last_success >= last_failure):
        return "可用但本场缺失", "源近期成功过，但本场未匹配到数据"
    if failure and (not success or last_failure >= last_success):
        return "最近失败", str(item.get("last_error") or "最近抓取失败")
    return "未验证", "还没有稳定抓取记录"


def source_audit(match: dict[str, Any], odds_history: list[dict[str, Any]], group_context: dict[str, Any] | None) -> dict[str, Any]:
    sources = {str(source.get("source_id")): source for source in load_sources()}
    health = load_source_health()

    official_rows = [
        row
        for row in odds_history
        if str(row.get("source", "")).startswith("sporttery_official")
        or row.get("bookmaker") == "中国体育彩票"
    ]
    calculator_rows = [row for row in odds_history if row.get("source") == "sporttery_mobile_calculator"]
    manual_rows = [row for row in odds_history if row.get("source") == "manual"]
    aicai_rows = [row for row in odds_history if str(row.get("source", "")).startswith("aicai_")]
    market_rows = [row for row in odds_history if row.get("market") in {"h2h", "胜平负", "让球胜平负", "总进球", "比分", "半全场"}]
    has_fifa = fifa_rank_value(match, "home") is not None and fifa_rank_value(match, "away") is not None
    has_formal = bool(match.get("formal_competition_strength"))
    has_process = bool(match.get("match_process_rating") or match.get("match_process_stats") or match.get("live_match_stats"))
    has_lineup = bool(match.get("lineup_status") == "confirmed")
    has_injury = bool(match.get("injury_notes"))

    official_status, official_note = source_status_from_health(
        "sporttery_official_match_list",
        len([row for row in official_rows if row.get("source") == "sporttery_official_match_list"]),
        health,
        bool(sources.get("sporttery_official_match_list", {}).get("enabled", True)),
    )
    calculator_status, calculator_note = source_status_from_health(
        "sporttery_mobile_calculator",
        len(calculator_rows),
        health,
        bool(sources.get("sporttery_mobile_calculator", {}).get("enabled", True)),
    )
    aicai_status, aicai_note = source_status_from_health(
        "aicai_worldcup_stats",
        len(aicai_rows),
        health,
        bool(sources.get("aicai_worldcup_stats", {}).get("enabled", True)),
    )
    standings_status, standings_note = source_status_from_health(
        "bing_worldcup_standings",
        1 if group_context else 0,
        health,
        bool(sources.get("bing_worldcup_standings", {}).get("enabled", True)),
    )
    process_status, process_note = source_status_from_health(
        "msn_worldcup_process",
        1 if has_process else 0,
        health,
        bool(sources.get("msn_worldcup_process", {}).get("enabled", False)),
    )

    rows = [
        {
            "tier": "A",
            "name": "体彩官方可下单数据",
            "status": official_status,
            "ok": bool(official_rows),
            "impact": "决定能买什么、让几球、SP是多少。缺失时只能按手动或历史快照参考，不能强行给正式下单项。",
            "detail": official_note,
        },
        {
            "tier": "A+",
            "name": "体彩计算器补充玩法",
            "status": calculator_status,
            "ok": bool(calculator_rows),
            "impact": "补充比分、总进球、半全场等细玩法。缺失时这些玩法只保留概率池，不应重仓。",
            "detail": calculator_note,
        },
        {
            "tier": "B",
            "name": "市场走势与盘口参考",
            "status": aicai_status,
            "ok": bool(aicai_rows),
            "impact": "用于看欧赔、让球、大小球变化。缺失时市场方向和收盘变化判断变弱。",
            "detail": aicai_note,
        },
        {
            "tier": "C",
            "name": "国家队基础实力",
            "status": "已拿到" if has_fifa and match.get("home_elo") and match.get("away_elo") else "部分缺失",
            "ok": bool(has_fifa and match.get("home_elo") and match.get("away_elo")),
            "impact": "用于判断强弱底盘。缺少排名或 Elo 时，不能过度相信盘口方向。",
            "detail": "FIFA 排名和 Elo 同时存在" if has_fifa and match.get("home_elo") and match.get("away_elo") else "FIFA 排名或 Elo 不完整",
        },
        {
            "tier": "C",
            "name": "预选赛/洲际杯正式赛表现",
            "status": "已拿到" if has_formal else "缺失",
            "ok": has_formal,
            "impact": "用于国家队近期硬表现修正。缺失时只靠排名，容易低估状态变化。",
            "detail": "存在正式赛强度字段" if has_formal else "未配置 formal_competition_strength",
        },
        {
            "tier": "C",
            "name": "小组积分与出线动机",
            "status": standings_status,
            "ok": bool(group_context),
            "impact": "用于判断抢分、轮换、默契和净胜球需求。缺失时第三轮尤其容易失真。",
            "detail": standings_note,
        },
        {
            "tier": "D",
            "name": "过程统计/赛后技术数据",
            "status": process_status,
            "ok": has_process,
            "impact": "用于复盘谁是真强、谁是运气球。缺失时赛后调参只能依赖比分和市场。",
            "detail": process_note,
        },
        {
            "tier": "D",
            "name": "伤停与首发",
            "status": "已拿到" if has_lineup and has_injury else "待临场确认",
            "ok": has_lineup and has_injury,
            "impact": "用于最后一轮校准。缺失时临场建议要降档，尤其是深盘强队。",
            "detail": "首发和伤停均已确认" if has_lineup and has_injury else "首发或伤停未确认",
        },
    ]

    score = 0
    weights = {"A": 24, "A+": 10, "B": 14, "C": 14, "D": 8}
    for row in rows:
        if row["ok"]:
            score += weights.get(row["tier"], 8)
        elif row["tier"] == "A" and manual_rows:
            score += 10
            row["status"] = "手动兜底"
            row["detail"] = "未抓到官方本场数据，但存在手动赔率或历史快照"
    score = min(100, score)
    if score >= 78:
        level = "数据充分"
        model_mode = "正常计算"
        confidence_penalty = 0
    elif score >= 58:
        level = "可预测但需谨慎"
        model_mode = "降级计算"
        confidence_penalty = 6
    elif score >= 40:
        level = "数据偏少"
        model_mode = "方向参考"
        confidence_penalty = 12
    else:
        level = "只适合观察"
        model_mode = "低置信参考"
        confidence_penalty = 18

    missing_impacts = [row["impact"] for row in rows if not row["ok"]][:5]
    if not market_rows:
        missing_impacts.insert(0, "缺少赔率/SP，无法判断官方价格是否值得买。")
    return {
        "score": score,
        "level": level,
        "model_mode": model_mode,
        "confidence_penalty": confidence_penalty,
        "rows": rows,
        "missing_impacts": missing_impacts[:6],
        "official_rows": len(official_rows),
        "manual_rows": len(manual_rows),
        "market_rows": len(market_rows),
    }


def data_completeness(match: dict[str, Any], odds_history: list[dict[str, Any]]) -> dict[str, Any]:
    group_context = find_group_context(match)
    has_aicai = any(str(row.get("source", "")).startswith("aicai_") for row in odds_history)
    audit = source_audit(match, odds_history, group_context)
    checks = [
        ("赛程匹配", bool(match.get("match_id") and match.get("kickoff")), 10, "没有准确比赛和时间，无法对齐体彩和赛程。"),
        ("Elo", bool(match.get("home_elo") and match.get("away_elo")), 10, "基础实力底盘会变弱。"),
        ("FIFA世界排名", fifa_rank_value(match, "home") is not None and fifa_rank_value(match, "away") is not None, 7, "国家队强弱侧面参考不足。"),
        ("预选赛/洲际杯正式赛", bool(match.get("formal_competition_strength")), 10, "近期正式赛状态无法修正。"),
        ("近期/过程数据", bool(match.get("expected_goals") or match.get("process_notes")), 10, "进攻/防守质量只能用默认估计。"),
        ("权威侧面源", bool(match.get("authority_side_strength")), 7, "媒体和权威数据侧面强度缺失。"),
        ("赛中/赛后过程统计", bool(match.get("match_process_rating") or match.get("match_process_stats") or match.get("live_match_stats")), 7, "复盘时无法区分实力与偶然。"),
        ("赔率/SP", bool(odds_history), 14, "无法做去水概率和价值判断。"),
        ("赔率历史", len({captured_at_key(r) for r in odds_history if captured_at_key(r)}) >= 2, 8, "看不到赔率波动，只能看单点价格。"),
        ("爱彩盘口/赛果统计", has_aicai, 8, "市场走势、让球和大小球参考不足。"),
        ("伤停", bool(match.get("injury_notes")), 11, "临场人员风险未确认。"),
        ("首发", bool(match.get("lineup_status") == "confirmed"), 11, "赛前最后校准不足。"),
        ("小组积分榜", bool(group_context), 8, "出线动机和轮换风险不清楚。"),
        ("天气/裁判/场地", bool(match.get("weather_notes") or match.get("referee_notes")), 7, "红牌、点球、场地节奏风险无法修正。"),
        ("战术标签", bool(match.get("tactical_notes")), 4, "打法相克只能粗略判断。"),
    ]
    score = min(100, sum(weight for _, ok, weight, _ in checks if ok))
    if score >= 82:
        level = "数据充分"
    elif score >= 65:
        level = "可正常预测"
    elif score >= 50:
        level = "谨慎预测"
    else:
        level = "方向参考"
    return {
        "score": score,
        "level": level,
        "source_audit": audit,
        "confidence_penalty": audit["confidence_penalty"],
        "items": [
            {"name": name, "ok": ok, "weight": weight, "impact": impact}
            for name, ok, weight, impact in checks
        ],
    }


def dimension_scores(match: dict[str, Any], market_signal: dict[str, Any], upset: dict[str, Any]) -> list[dict[str, Any]]:
    configured = match.get("dimension_scores", {})
    group_context = find_group_context(match)
    rows = []
    for key, label, weight in DIMENSIONS:
        score = configured.get(key)
        if score is None:
            if key == "strength":
                score = clamp((match.get("home_elo", 1800) - match.get("away_elo", 1800)) / 160, -3, 3)
            elif key == "fifa_ranking":
                score = fifa_ranking_score(match)
            elif key == "formal_competition_strength":
                score = formal_competition_strength_score(match)
            elif key == "authority_side_strength":
                score = authority_side_strength_score(match)
            elif key == "match_process_rating":
                score = match_process_rating_score(match)
            elif key == "upset":
                score = -clamp(upset["score"] / 2, 0, 3)
            elif key == "motivation" and group_context:
                home = group_context.get("home") or {}
                away = group_context.get("away") or {}
                home_points = float(home.get("points", 0))
                away_points = float(away.get("points", 0))
                home_gd = float(home.get("goal_diff", 0))
                away_gd = float(away.get("goal_diff", 0))
                score = clamp((home_points - away_points) * 0.35 + (home_gd - away_gd) * 0.12, -2, 2)
            else:
                score = 0
        advantage = "主队" if score > 0.35 else "客队" if score < -0.35 else "均衡/待确认"
        rows.append(
            {
                "key": key,
                "label": label,
                "weight": weight,
                "score": round(float(score), 2),
                "advantage": advantage,
            }
        )
    if market_signal.get("latest_probs"):
        rows[0]["market_direction"] = market_signal["direction"]
    return rows


def probability_gap(model_probs: dict[str, float], market_probs: dict[str, float] | None) -> dict[str, Any]:
    if not market_probs:
        return {"level": "无市场数据", "max_gap": None, "gaps": None}
    gaps = {k: model_probs[k] - market_probs[k] for k in model_probs}
    max_gap = max(abs(v) for v in gaps.values())
    if max_gap < 0.03:
        level = "一致"
    elif max_gap < 0.08:
        level = "轻微分歧"
    elif max_gap < 0.13:
        level = "明显分歧"
    else:
        level = "高分歧"
    return {"level": level, "max_gap": max_gap, "gaps": gaps}


def build_prediction(match: dict[str, Any], odds_history: list[dict[str, Any]]) -> dict[str, Any]:
    market = derive_market_signal(odds_history)
    market_context = aicai_market_context(odds_history)
    upset = upset_profile(match)
    completeness = data_completeness(match, odds_history)
    source_audit_payload = completeness["source_audit"]
    source_penalty = int(source_audit_payload.get("confidence_penalty", 0))
    group_context = find_group_context(match)

    base = elo_probabilities(float(match.get("home_elo", 1800)), float(match.get("away_elo", 1800)), match.get("neutral", True))
    if match.get("manual_probabilities"):
        base = blend_probs(base, normalize_probs(match["manual_probabilities"]), 0.55)

    h2h_odds = latest_h2h_odds(odds_history, match)
    market_sp = latest_sporttery_sp_map(odds_history)
    effective_handicap = latest_sporttery_handicap(odds_history)
    if effective_handicap is None:
        effective_handicap = match.get("sporttery_handicap")
    market_base = market.get("latest_probs") or implied_probabilities(h2h_odds or {}) or base
    value_deltas = feature_deltas(match, market, upset)
    value_probs = softmax_market_model(market_base, value_deltas)
    favorite = "home" if base["home"] >= base["away"] else "away"
    scenarios: list[PredictionResult] = []

    scenario_probs = {
        "baseline": base,
        "market": blend_probs(base, market.get("latest_probs"), market.get("weight", 0.0)),
        "live": deepcopy(base),
        "conservative": normalize_probs({"home": base["home"] * 0.92, "draw": base["draw"] * 1.22, "away": base["away"] * 0.92}),
        "open": normalize_probs({"home": base["home"] * 1.07, "draw": base["draw"] * 0.78, "away": base["away"] * 1.07}),
        "upset": apply_adjustment(base, upset["adjustment"], favorite),
    }

    live_adj = match.get("live_adjustment", {})
    if live_adj:
        scenario_probs["live"] = normalize_probs({k: scenario_probs["live"][k] + float(live_adj.get(k, 0)) for k in scenario_probs["live"]})
    else:
        scenario_probs["live"] = scenario_probs["market"]

    for key, probs in scenario_probs.items():
        xg = estimate_expected_goals(match, probs, key)
        deep_context = deep_favorite_context(match, probs, xg, effective_handicap)
        scenario_context = {
            "open_game_profile": open_game_profile(match, probs, xg),
            "variance_profile": variance_profile(match, probs, xg, effective_handicap),
            "favorite_side": deep_context["favorite_side"],
            "deep_favorite_profile": deep_context["deep_favorite_profile"],
            "favorite_stall_profile": favorite_stall_profile(match, probs, xg, effective_handicap),
            "model_probs": probs,
            "xg": xg,
            "handicap": effective_handicap,
        }
        matrix = score_matrix(xg["home"], xg["away"], mode=key, context=scenario_context)
        top_scores = ranked_scorelines(matrix, limit=8, context=scenario_context)
        goal_bins: dict[str, float] = defaultdict(float)
        over_25 = 0.0
        btts = 0.0
        for row in matrix:
            total_goals = row["home_goals"] + row["away_goals"]
            bucket = "7+" if total_goals >= 7 else str(total_goals)
            goal_bins[bucket] += row["probability"]
            if total_goals > 2.5:
                over_25 += row["probability"]
            if row["home_goals"] > 0 and row["away_goals"] > 0:
                btts += row["probability"]
        total_summary = total_goals_summary(matrix)
        ou_lines = over_under_lines(matrix)
        notes = []
        if key == "market" and market.get("latest_probs"):
            notes.append(f"{market['direction']}，市场权重 {market.get('weight', 0):.2f}")
        if key == "upset":
            notes.append(f"爆冷触发器 {upset['score']:.1f}，等级 {upset['level']}")
        if key == "conservative":
            notes.append("假设比赛进入慢节奏和低比分区间")
        if key == "open":
            notes.append("假设早进球或双方必须争胜导致空间拉开")

        scenarios.append(
            PredictionResult(
                scenario=key,
                label=SCENARIO_LABELS[key],
                probabilities={k: round(v, 4) for k, v in probs.items()},
                expected_goals=xg,
                top_scores=[
                    {
                        "score": row["score"],
                        "probability": round(row["probability"], 4),
                        "score_group": row["score_group"],
                        "score_priority": row["score_priority"],
                        "score_note": row["score_note"],
                    }
                    for row in top_scores
                ],
                score_grid=[
                    {"score": row["score"], "probability": round(row["probability"], 4)}
                    for row in score_grid(matrix)
                ],
                goal_distribution=[
                    {"goals": k, "probability": round(goal_bins[k], 4)}
                    for k in ["0", "1", "2", "3", "4", "5", "6", "7+"]
                ],
                total_goals=total_summary,
                over_under_lines=ou_lines,
                over_25=round(over_25, 4),
                btts=round(btts, 4),
                confidence=clamp(
                    completeness["score"]
                    - source_penalty
                    - (8 if probability_gap(base, market.get("latest_probs"))["level"] in {"明显分歧", "高分歧"} else 0),
                    30,
                    92,
                ),
                notes=notes,
            )
        )

    baseline = next(item for item in scenarios if item.scenario == "baseline")
    value_xg = estimate_expected_goals(match, value_probs, "market")
    value_deep_context = deep_favorite_context(match, value_probs, value_xg, effective_handicap)
    value_context = {
        "open_game_profile": open_game_profile(match, value_probs, value_xg),
        "variance_profile": variance_profile(match, value_probs, value_xg, effective_handicap),
        "favorite_side": value_deep_context["favorite_side"],
        "deep_favorite_profile": value_deep_context["deep_favorite_profile"],
        "favorite_stall_profile": favorite_stall_profile(match, value_probs, value_xg, effective_handicap),
        "model_probs": value_probs,
        "xg": value_xg,
        "handicap": effective_handicap,
    }
    value_matrix = score_matrix(value_xg["home"], value_xg["away"], mode="market", context=value_context)
    value_top_scores = ranked_scorelines(value_matrix, limit=8, context=value_context)
    sporttery = build_sporttery_outputs(match, value_probs, value_matrix, value_xg, upset, market, h2h_odds, market_sp)
    gap = probability_gap(baseline.probabilities, market.get("latest_probs"))
    return {
        "match": match,
        "market_signal": market,
        "market_context": market_context,
        "value_model": {
            "market_probs": {key: round(value, 4) for key, value in market_base.items()},
            "deltas": value_deltas,
            "fifa_ranking_score": round(fifa_ranking_score(match), 3),
            "formal_competition_strength": round(formal_competition_strength_score(match), 3),
            "lambda_adjustments": lambda_adjustment_profile(match, value_probs, value_xg),
            "probabilities": {key: round(value, 4) for key, value in value_probs.items()},
            "expected_goals": value_xg,
            "top_scores": [
                {
                    "score": row["score"],
                    "probability": round(row["probability"], 4),
                    "score_group": row["score_group"],
                    "score_priority": row["score_priority"],
                    "score_note": row["score_note"],
                }
                for row in value_top_scores
            ],
            "score_grid": [
                {"score": row["score"], "probability": round(row["probability"], 4)}
                for row in score_grid(value_matrix)
            ],
            "total_goals": total_goals_summary(value_matrix),
            "over_under_lines": over_under_lines(value_matrix),
        },
        "sporttery": sporttery,
        "upset": upset,
        "data_completeness": completeness,
        "source_audit": source_audit_payload,
        "group_context": group_context,
        "dimension_scores": dimension_scores(match, market, upset),
        "model_market_gap": gap,
        "scenarios": [scenario.__dict__ for scenario in scenarios],
        "summary": build_summary(match, scenarios, market, upset, completeness, gap, value_probs, value_top_scores),
    }


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_summary(
    match: dict[str, Any],
    scenarios: list[PredictionResult],
    market: dict[str, Any],
    upset: dict[str, Any],
    completeness: dict[str, Any],
    gap: dict[str, Any],
    value_probs: dict[str, float] | None = None,
    value_top_scores: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    baseline = next(item for item in scenarios if item.scenario == "baseline")
    market_scenario = next(item for item in scenarios if item.scenario == "market")
    summary_probs = value_probs or market_scenario.probabilities
    leader_key = max(summary_probs, key=lambda k: summary_probs[k])
    leader = {"home": match["home_team"], "draw": "平局", "away": match["away_team"]}[leader_key]
    source_scores = value_top_scores or market_scenario.top_scores
    best_scores = [row["score"] for row in source_scores[:3]]
    return {
        "main_lean": leader,
        "score_group": best_scores,
        "market_direction": market["direction"],
        "upset_level": upset["level"],
        "folk_parallel": folk_parallel_summary_with_context(match, summary_probs, leader, best_scores),
        "confidence": int(baseline.confidence),
        "data_score": completeness["score"],
        "data_level": completeness.get("source_audit", {}).get("level") or completeness.get("level", "待确认"),
        "source_level": completeness.get("source_audit", {}).get("level", "待确认"),
        "model_mode": completeness.get("source_audit", {}).get("model_mode", "正常计算"),
        "missing_impacts": completeness.get("source_audit", {}).get("missing_impacts", []),
        "gap_level": gap["level"],
        "reference": (
            f"最终模型倾向 {leader}；比分参考 {' / '.join(best_scores)}；"
            f"去水与特征修正后主/平/客为 {pct(summary_probs['home'])} / "
            f"{pct(summary_probs['draw'])} / {pct(summary_probs['away'])}；"
            f"数据状态为 {completeness.get('source_audit', {}).get('level') or completeness.get('level', '待确认')}，"
            f"{completeness.get('source_audit', {}).get('model_mode', '正常计算')}。"
        ),
    }
