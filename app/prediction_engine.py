from __future__ import annotations

import math
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

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
    ("strength", "基础实力 / Elo / 市场概率", 20),
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


def variance_profile(match: dict[str, Any], probs: dict[str, float], xg: dict[str, float]) -> dict[str, Any]:
    open_profile = open_game_profile(match, probs, xg)
    upset = upset_profile(match)
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

    return {
        "overdispersion": round(clamp(overdispersion, 0, 0.34), 3),
        "low_score_shrink": round(clamp(low_score_shrink, 0, 0.20), 3),
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


def apply_goal_distribution_adjustments(rows: list[dict[str, Any]], context: dict[str, Any] | None) -> None:
    if not context:
        return
    variance = context.get("variance_profile") or {}
    overdispersion = float(variance.get("overdispersion", 0) or 0)
    low_score_shrink = float(variance.get("low_score_shrink", 0) or 0)
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
        open_effect = clamp(float(open_profile.get("score", 0)) / 5, 0, 1)
        if deep_favorite:
            shape_penalty = 0.006 * max(0, total_goals - 5) + 0.003 * max(0, margin - 4)
            if favorite == "home" and row["home_goals"] > row["away_goals"] and margin >= 3:
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
        if deep_favorite and total_goals >= 3 and margin >= 3:
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
        if context and context.get("deep_favorite_profile") and total_goals >= 3 and margin >= 3:
            meta = {
                "score_group": "深盘大胜比分",
                "score_priority": 3,
                "score_note": "和深盘让胜方向一致，适合小额比分池，不宜重仓单压",
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
    context_seed = {"deep_favorite_profile": deep_favorite_profile, "favorite_side": favorite_side}
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
        "score_betting_allowed": balanced or (model_probs["draw"] >= 0.27 and low_draw_core),
        "one_goal_core": one_goal_core,
        "low_draw_core": low_draw_core,
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
                    item["risk_score"] = max(75, int(item.get("risk_score") or 75))
                    item["risk_level"] = risk_level(item["risk_score"])
                    if item.get("decision") in {"放弃", "高风险观察"} and item.get("sp"):
                        item["decision"] = "高风险观察"
                        item["reason"] = "深盘强队存在大胜尾部，只能小额保护"
                    item["risk_adjusted_score"] = round(float(item.get("risk_adjusted_score", -1)) + 0.10, 4)
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
                item["score_bet_allowed"] = False

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


def derive_market_signal(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history:
        return {"direction": "无赔率数据", "strength": 0, "latest_probs": None, "movement": {}, "bookmakers": 0, "snapshots": 0, "weight": 0.0}

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in sorted(history, key=lambda x: x["captured_at"]):
        if row["market"] == "h2h":
            grouped[row["bookmaker"]].append(row)

    latest_by_book: list[dict[str, float]] = []
    first_by_book: list[dict[str, float]] = []
    for rows in grouped.values():
        by_time: dict[str, dict[str, float]] = defaultdict(dict)
        for row in rows:
            by_time[row["captured_at"]][row["selection"]] = float(row["odds_decimal"])
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
    snapshot_count = len({row["captured_at"] for row in history if row.get("market") == "h2h"})
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

    balance = clamp(2 - abs(strength), 0, 2)
    low_tempo = clamp(-tempo, 0, 3)
    draw_delta = (
        low_tempo * 0.035
        + balance * 0.030
        + upset_strength * 0.025
        - abs(strength) * 0.020
        - abs(formal) * 0.012
    )
    return {"home": round(home_core, 4), "draw": round(draw_delta, 4), "away": round(away_core, 4)}


def latest_h2h_odds(history: list[dict[str, Any]], match: dict[str, Any]) -> dict[str, float] | None:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for row in history:
        if row.get("market") == "h2h" and row.get("selection") in {"home", "draw", "away"}:
            grouped[row["captured_at"]][row["selection"]].append(float(row["odds_decimal"]))
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
            grouped[row["captured_at"]][row["selection"]].append(float(row["odds_decimal"]))
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
        rows = sorted(rows, key=lambda row: row["captured_at"])
        first = float(rows[0]["odds_decimal"])
        latest = float(rows[-1]["odds_decimal"])
        return {"first": round(first, 3), "latest": round(latest, 3), "movement": round(latest - first, 3)}

    def latest_value(market: str, selection: str) -> float | None:
        rows = [row for row in aicai_rows if row.get("market") == market and row.get("selection") == selection]
        if not rows:
            return None
        return round(float(sorted(rows, key=lambda row: row["captured_at"])[-1]["odds_decimal"]), 3)

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
        "snapshots": len({row["captured_at"] for row in aicai_rows}),
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
    for row in sorted(history, key=lambda item: item["captured_at"]):
        if row.get("market") in sporttery_markets:
            output[(row["market"], row["selection"])] = (float(row["odds_decimal"]), row.get("source", "odds_history"))
        elif row.get("market") == "sporttery_handicap" and row.get("selection") == "H":
            output[("__meta__", "handicap")] = (float(row["odds_decimal"]), row.get("source", "odds_history"))
        elif row.get("market") in pool_meta_markets:
            output[(row["market"], str(row["selection"]).upper())] = (float(row["odds_decimal"]), row.get("source", "odds_history"))
    return output


def latest_sporttery_handicap(history: list[dict[str, Any]]) -> int | None:
    handicap = None
    for row in sorted(history, key=lambda item: item["captured_at"]):
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
        if context.get("deep_favorite_profile") and name == "低比分池":
            action = "不建议"
        elif name == "开放比分池" and open_score >= 3.0 and max_risk < 82:
            action = "可做小复式"
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
    if context.get("deep_favorite_profile"):
        score_cap = 0.06
        score_combo_cap = 0.03
        tail_cap = 0.02
    elif context.get("balanced_matchup"):
        score_cap = 0.12
        score_combo_cap = 0.06
        tail_cap = 0.0
    else:
        score_cap = 0.08
        score_combo_cap = 0.04
        tail_cap = 0.01
    return {
        "direction_min": 0.70,
        "score_cap": score_cap,
        "score_combo_cap": score_combo_cap,
        "deep_tail_cap": tail_cap,
        "single_score_cap": min(0.04, score_cap / 2),
        "hard_rules": [
            "比分仓不得超过上限",
            "比分串不得高于比分单场仓",
            "深盘尾部保护只允许小额",
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
    options = apply_recommendation_rules(options, rec_context, handicap)
    play_priority = {"胜平负": 5, "让球胜平负": 4, "总进球": 3, "半全场": 2, "比分": 1}
    ranked = sorted(
        options,
        key=lambda item: (
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
        "candidate_pool": [item for item in available if item["decision"] in {"可小注", "观察", "高风险观察"}][:20],
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


def data_completeness(match: dict[str, Any], odds_history: list[dict[str, Any]]) -> dict[str, Any]:
    group_context = find_group_context(match)
    has_aicai = any(str(row.get("source", "")).startswith("aicai_") for row in odds_history)
    checks = [
        ("赛程匹配", bool(match.get("match_id") and match.get("kickoff")), 10),
        ("Elo / FIFA", bool(match.get("home_elo") and match.get("away_elo")), 12),
        ("预选赛/洲际杯正式赛", bool(match.get("formal_competition_strength")), 10),
        ("近期/过程数据", bool(match.get("expected_goals") or match.get("process_notes")), 10),
        ("权威侧面源", bool(match.get("authority_side_strength")), 7),
        ("赛中/赛后过程统计", bool(match.get("match_process_rating") or match.get("match_process_stats") or match.get("live_match_stats")), 7),
        ("赔率", bool(odds_history), 14),
        ("赔率历史", len({r["captured_at"] for r in odds_history}) >= 2, 8),
        ("爱彩盘口/赛果统计", has_aicai, 8),
        ("伤停", bool(match.get("injury_notes")), 11),
        ("首发", bool(match.get("lineup_status") == "confirmed"), 11),
        ("小组积分榜", bool(group_context), 8),
        ("天气/裁判/场地", bool(match.get("weather_notes") or match.get("referee_notes")), 7),
        ("战术标签", bool(match.get("tactical_notes")), 4),
    ]
    score = min(100, sum(weight for _, ok, weight in checks if ok))
    return {
        "score": score,
        "items": [{"name": name, "ok": ok, "weight": weight} for name, ok, weight in checks],
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
            "variance_profile": variance_profile(match, probs, xg),
            "favorite_side": deep_context["favorite_side"],
            "deep_favorite_profile": deep_context["deep_favorite_profile"],
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
                confidence=clamp(completeness["score"] - (8 if probability_gap(base, market.get("latest_probs"))["level"] in {"明显分歧", "高分歧"} else 0), 35, 92),
                notes=notes,
            )
        )

    baseline = next(item for item in scenarios if item.scenario == "baseline")
    value_xg = estimate_expected_goals(match, value_probs, "market")
    value_deep_context = deep_favorite_context(match, value_probs, value_xg, effective_handicap)
    value_context = {
        "open_game_profile": open_game_profile(match, value_probs, value_xg),
        "variance_profile": variance_profile(match, value_probs, value_xg),
        "favorite_side": value_deep_context["favorite_side"],
        "deep_favorite_profile": value_deep_context["deep_favorite_profile"],
        "model_probs": value_probs,
        "xg": value_xg,
        "handicap": effective_handicap,
    }
    value_matrix = score_matrix(value_xg["home"], value_xg["away"], mode="market", context=value_context)
    sporttery = build_sporttery_outputs(match, value_probs, value_matrix, value_xg, upset, market, h2h_odds, market_sp)
    gap = probability_gap(baseline.probabilities, market.get("latest_probs"))
    return {
        "match": match,
        "market_signal": market,
        "market_context": market_context,
        "value_model": {
            "market_probs": {key: round(value, 4) for key, value in market_base.items()},
            "deltas": value_deltas,
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
                for row in ranked_scorelines(value_matrix, limit=8, context=value_context)
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
        "group_context": group_context,
        "dimension_scores": dimension_scores(match, market, upset),
        "model_market_gap": gap,
        "scenarios": [scenario.__dict__ for scenario in scenarios],
        "summary": build_summary(match, scenarios, market, upset, completeness, gap),
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
) -> dict[str, Any]:
    baseline = next(item for item in scenarios if item.scenario == "baseline")
    market_scenario = next(item for item in scenarios if item.scenario == "market")
    leader_key = max(baseline.probabilities, key=lambda k: baseline.probabilities[k])
    leader = {"home": match["home_team"], "draw": "平局", "away": match["away_team"]}[leader_key]
    best_scores = [row["score"] for row in baseline.top_scores[:3]]
    return {
        "main_lean": leader,
        "score_group": best_scores,
        "market_direction": market["direction"],
        "upset_level": upset["level"],
        "confidence": int(baseline.confidence),
        "data_score": completeness["score"],
        "gap_level": gap["level"],
        "reference": (
            f"基准倾向 {leader}；比分参考 {' / '.join(best_scores)}；"
            f"市场修正后主/平/客为 {pct(market_scenario.probabilities['home'])} / "
            f"{pct(market_scenario.probabilities['draw'])} / {pct(market_scenario.probabilities['away'])}。"
        ),
    }
