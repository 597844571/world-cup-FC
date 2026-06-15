from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any


def actual_result(fixture: dict[str, Any]) -> str | None:
    home = fixture.get("home_score")
    away = fixture.get("away_score")
    if home is None or away is None:
        return None
    if home > away:
        return "home"
    if home < away:
        return "away"
    return "draw"


def predicted_result(snapshot: dict[str, Any]) -> str:
    probs = {
        "home": float(snapshot["home_prob"]),
        "draw": float(snapshot["draw_prob"]),
        "away": float(snapshot["away_prob"]),
    }
    return max(probs, key=probs.get)


def brier_score(snapshot: dict[str, Any], result: str) -> float:
    return sum((float(snapshot[f"{key}_prob"]) - (1.0 if key == result else 0.0)) ** 2 for key in ("home", "draw", "away"))


def log_loss(snapshot: dict[str, Any], result: str) -> float:
    prob = max(float(snapshot[f"{result}_prob"]), 0.0001)
    return -math.log(prob)


def score_hit(snapshot: dict[str, Any], fixture: dict[str, Any]) -> bool:
    top_score = snapshot.get("top_score")
    actual = f"{fixture.get('home_score')}-{fixture.get('away_score')}"
    return top_score == actual


def top2_hit(snapshot: dict[str, Any], result: str) -> bool:
    probs = [
        ("home", float(snapshot["home_prob"])),
        ("draw", float(snapshot["draw_prob"])),
        ("away", float(snapshot["away_prob"])),
    ]
    top_two = {key for key, _ in sorted(probs, key=lambda item: item[1], reverse=True)[:2]}
    return result in top_two


def odds_for_result(odds_history: list[dict[str, Any]], result: str, captured_at: str | None = None) -> tuple[float | None, float | None]:
    selection_aliases = {
        "home": {"home", "胜"},
        "draw": {"draw", "平"},
        "away": {"away", "负"},
    }[result]
    rows = [
        row
        for row in odds_history
        if row.get("market") in {"h2h", "胜平负"}
        and str(row.get("selection")) in selection_aliases
        and row.get("odds_decimal")
    ]
    if not rows:
        return None, None
    rows = sorted(rows, key=lambda item: item.get("captured_at") or "")
    pre_rows = [row for row in rows if captured_at and (row.get("captured_at") or "") <= captured_at]
    pre = pre_rows[-1] if pre_rows else rows[0]
    close = rows[-1]
    return float(pre["odds_decimal"]), float(close["odds_decimal"])


def evaluate_fixture(fixture: dict[str, Any], snapshots: list[dict[str, Any]], odds_history: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    result = actual_result(fixture)
    if not result:
        return []
    odds_history = odds_history or []
    evaluated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for snapshot in snapshots:
        predicted = predicted_result(snapshot)
        prediction_prob = float(snapshot[f"{predicted}_prob"])
        pre_match_sp, closing_sp = odds_for_result(odds_history, predicted, snapshot.get("captured_at"))
        roi = None
        if closing_sp:
            roi = closing_sp - 1 if predicted == result else -1.0
        rows.append(
            {
                "match_id": fixture["match_id"],
                "evaluated_at": evaluated_at,
                "snapshot_id": snapshot["id"],
                "scenario": snapshot["scenario"],
                "actual_score": f"{fixture.get('home_score')}-{fixture.get('away_score')}",
                "actual_result": result,
                "predicted_result": predicted,
                "prediction_prob": prediction_prob,
                "pre_match_sp": pre_match_sp,
                "closing_sp": closing_sp,
                "roi": roi,
                "top1_hit": predicted == result,
                "top2_hit": top2_hit(snapshot, result),
                "brier_score": brier_score(snapshot, result),
                "log_loss": log_loss(snapshot, result),
                "score_hit": score_hit(snapshot, fixture),
                "notes": f"actual_score={fixture.get('home_score')}-{fixture.get('away_score')}",
            }
        )
    return rows


def summarize_backtests(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {
            "count": 0,
            "top1_accuracy": None,
            "top2_accuracy": None,
            "score_accuracy": None,
            "avg_brier": None,
            "avg_log_loss": None,
            "avg_roi": None,
            "by_scenario": [],
            "calibration_buckets": [],
            "tuning_suggestions": ["当前没有已完结且已归档的预测样本，暂不建议调参。"],
        }
    by_scenario: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        by_scenario.setdefault(row["scenario"], []).append(row)
    return {
        "count": len(results),
        "top1_accuracy": avg(results, "top1_hit"),
        "top2_accuracy": avg(results, "top2_hit"),
        "score_accuracy": avg(results, "score_hit"),
        "avg_brier": avg(results, "brier_score"),
        "avg_log_loss": avg(results, "log_loss"),
        "avg_roi": avg([row for row in results if row.get("roi") is not None], "roi") if any(row.get("roi") is not None for row in results) else None,
        "calibration_buckets": calibration_buckets(results),
        "by_scenario": [
            {
                "scenario": scenario,
                "count": len(rows),
                "top1_accuracy": avg(rows, "top1_hit"),
                "top2_accuracy": avg(rows, "top2_hit"),
                "score_accuracy": avg(rows, "score_hit"),
                "avg_brier": avg(rows, "brier_score"),
                "avg_log_loss": avg(rows, "log_loss"),
                "avg_roi": avg([row for row in rows if row.get("roi") is not None], "roi") if any(row.get("roi") is not None for row in rows) else None,
            }
            for scenario, rows in sorted(by_scenario.items())
        ],
        "tuning_suggestions": tuning_suggestions(by_scenario),
    }


def avg(rows: list[dict[str, Any]], key: str) -> float:
    return sum(float(row[key]) for row in rows) / len(rows)


def calibration_buckets(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = {
        "0-40%": [],
        "40-50%": [],
        "50-60%": [],
        "60-70%": [],
        "70%+": [],
    }
    for row in results:
        max_prob = max_probability_from_row(row)
        if max_prob < 0.4:
            key = "0-40%"
        elif max_prob < 0.5:
            key = "40-50%"
        elif max_prob < 0.6:
            key = "50-60%"
        elif max_prob < 0.7:
            key = "60-70%"
        else:
            key = "70%+"
        buckets[key].append(row)
    return [
        {
            "bucket": bucket,
            "count": len(rows),
            "accuracy": avg(rows, "top1_hit") if rows else None,
            "avg_brier": avg(rows, "brier_score") if rows else None,
        }
        for bucket, rows in buckets.items()
    ]


def max_probability_from_row(row: dict[str, Any]) -> float:
    # Historical rows do not store the three probabilities, so approximate confidence bucket
    # from whether the prediction was wrong and log loss. Future schema can persist max_prob.
    if row["top1_hit"]:
        return min(0.85, math.exp(-float(row["log_loss"])))
    return min(0.85, 1 - math.exp(-float(row["log_loss"])))


def tuning_suggestions(by_scenario: dict[str, list[dict[str, Any]]]) -> list[str]:
    suggestions: list[str] = []
    baseline = by_scenario.get("baseline", [])
    market = by_scenario.get("market", [])
    upset = by_scenario.get("upset", [])
    conservative = by_scenario.get("conservative", [])
    if baseline and market and avg(market, "brier_score") + 0.02 < avg(baseline, "brier_score"):
        suggestions.append("市场校准模型 Brier 明显优于基准模型，可小幅提高动态市场权重上限。")
    if baseline and market and avg(market, "brier_score") > avg(baseline, "brier_score") + 0.02:
        suggestions.append("市场校准模型弱于基准模型，检查赔率源质量或降低市场权重。")
    if upset and avg(upset, "top2_hit") > 0.75:
        suggestions.append("爆冷情景 Top2 覆盖较好，高爆冷等级场可继续保留较大平局/弱队不败空间。")
    if conservative and avg(conservative, "brier_score") + 0.02 < avg(baseline or conservative, "brier_score"):
        suggestions.append("保守节奏模型表现较好，淘汰赛或低节奏场景应提高平局和低比分修正。")
    if baseline and avg(baseline, "log_loss") > 1.2:
        suggestions.append("基准模型 Log Loss 偏高，说明错误高置信预测较多，应降低置信度上限。")
    if not suggestions:
        suggestions.append("当前回测样本不足或各模型差异不明显，暂不建议大幅调参。")
    return suggestions
