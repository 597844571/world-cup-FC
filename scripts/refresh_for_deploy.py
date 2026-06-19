from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import SERVERLESS_PREDICTIONS_PATH, SERVERLESS_PREDICTION_SNAPSHOTS_PATH, save_json
from app.match_registry import load_matches
from app.odds_store import OddsStore, now_iso
from app.prediction_engine import build_prediction
from app.server import auto_refresh_cycle, load_refresh_status


def compact_prediction(match: dict, prediction: dict) -> dict:
    scenario = next(
        (item for item in prediction.get("scenarios", []) if item.get("scenario") == "market"),
        prediction.get("scenarios", [{}])[0],
    )
    sporttery = prediction.get("sporttery", {})
    return {
        "match_id": match["match_id"],
        "home_team": match["home_team"],
        "away_team": match["away_team"],
        "kickoff": match.get("kickoff"),
        "sporttery_handicap": sporttery.get("handicap") if sporttery else match.get("sporttery_handicap"),
        "summary": prediction.get("summary", {}),
        "market_scenario": {
            "probabilities": scenario.get("probabilities", {}),
            "top_scores": (scenario.get("top_scores") or [])[:8],
            "total_goals": scenario.get("total_goals"),
            "over_25": scenario.get("over_25"),
            "btts": scenario.get("btts"),
            "confidence": scenario.get("confidence"),
        },
        "sporttery": {
            "settlement": sporttery.get("settlement"),
            "action_summary": sporttery.get("action_summary"),
            "score_reference": sporttery.get("score_reference"),
            "candidate_pool": (sporttery.get("candidate_pool") or [])[:24],
            "compound_packages": sporttery.get("compound_packages") or [],
            "score_combo_pools": sporttery.get("score_combo_pools") or [],
        },
        "data_completeness": prediction.get("data_completeness", {}),
        "source_audit": prediction.get("source_audit", {}),
    }


def snapshot_rows(match: dict, prediction: dict, captured_at: str) -> list[dict]:
    data_score = int((prediction.get("data_completeness") or {}).get("score") or 0)
    rows = []
    for scenario in prediction.get("scenarios", []):
        probs = scenario.get("probabilities", {})
        top_score = (scenario.get("top_scores") or [{}])[0].get("score")
        rows.append(
            {
                "match_id": match["match_id"],
                "captured_at": captured_at,
                "scenario": scenario.get("scenario"),
                "home_prob": probs.get("home"),
                "draw_prob": probs.get("draw"),
                "away_prob": probs.get("away"),
                "top_score": top_score,
                "over_25": scenario.get("over_25"),
                "btts": scenario.get("btts"),
                "confidence": scenario.get("confidence"),
                "data_score": data_score,
            }
        )
    return rows


def main() -> int:
    store = OddsStore()
    summary = auto_refresh_cycle(store, reason="github-actions")
    matches = load_matches()
    captured_at = now_iso()
    predictions = []
    snapshots = []
    for match in matches:
        prediction = build_prediction(match, store.odds_history(match["match_id"]))
        predictions.append(compact_prediction(match, prediction))
        snapshots.extend(snapshot_rows(match, prediction, captured_at))

    save_json(
        SERVERLESS_PREDICTIONS_PATH,
        {
            "captured_at": captured_at,
            "refresh_status": load_refresh_status(),
            "matches": predictions,
        },
    )
    save_json(SERVERLESS_PREDICTION_SNAPSHOTS_PATH, snapshots)
    print(
        json.dumps(
            {
                "ok": True,
                "fixtures": summary.get("fixtures"),
                "matches": len(matches),
                "predictions": len(predictions),
                "snapshots": len(snapshots),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
