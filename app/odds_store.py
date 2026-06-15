from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DB_PATH, ensure_dirs


SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    kickoff TEXT,
    status TEXT DEFAULT 'scheduled',
    odds_event_id TEXT
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    odds_decimal REAL NOT NULL,
    FOREIGN KEY(match_id) REFERENCES matches(match_id)
);

CREATE INDEX IF NOT EXISTS idx_odds_match_time ON odds_snapshots(match_id, captured_at);

CREATE TABLE IF NOT EXISTS fixtures (
    match_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    competition TEXT,
    stage TEXT,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    kickoff TEXT,
    status TEXT NOT NULL DEFAULT 'scheduled',
    home_score INTEGER,
    away_score INTEGER,
    venue TEXT,
    raw_json TEXT
);

CREATE TABLE IF NOT EXISTS prediction_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    scenario TEXT NOT NULL,
    home_prob REAL NOT NULL,
    draw_prob REAL NOT NULL,
    away_prob REAL NOT NULL,
    top_score TEXT,
    over_25 REAL,
    btts REAL,
    confidence INTEGER,
    data_score INTEGER
);

CREATE TABLE IF NOT EXISTS backtest_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL,
    scenario TEXT NOT NULL,
    actual_score TEXT,
    actual_result TEXT NOT NULL,
    predicted_result TEXT NOT NULL,
    prediction_prob REAL,
    pre_match_sp REAL,
    closing_sp REAL,
    roi REAL,
    top1_hit INTEGER NOT NULL,
    top2_hit INTEGER NOT NULL,
    brier_score REAL NOT NULL,
    log_loss REAL NOT NULL,
    score_hit INTEGER NOT NULL,
    notes TEXT,
    FOREIGN KEY(snapshot_id) REFERENCES prediction_snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_prediction_match_time ON prediction_snapshots(match_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_backtest_match ON backtest_results(match_id, evaluated_at);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OddsStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        ensure_dirs()
        self.path = path
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(backtest_results)").fetchall()}
        columns = {
            "actual_score": "TEXT",
            "prediction_prob": "REAL",
            "pre_match_sp": "REAL",
            "closing_sp": "REAL",
            "roi": "REAL",
        }
        for name, column_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE backtest_results ADD COLUMN {name} {column_type}")

    def upsert_match(self, match: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO matches (match_id, home_team, away_team, kickoff, status, odds_event_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id) DO UPDATE SET
                    home_team=excluded.home_team,
                    away_team=excluded.away_team,
                    kickoff=excluded.kickoff,
                    status=excluded.status,
                    odds_event_id=excluded.odds_event_id
                """,
                (
                    match["match_id"],
                    match["home_team"],
                    match["away_team"],
                    match.get("kickoff"),
                    match.get("status", "scheduled"),
                    match.get("odds_event_id"),
                ),
            )

    def insert_snapshots(self, match_id: str, snapshots: list[dict[str, Any]], captured_at: str | None = None) -> int:
        if not snapshots:
            return 0
        ts = captured_at or now_iso()
        rows = [
            (
                match_id,
                item.get("captured_at", ts),
                item.get("source", "manual"),
                item.get("bookmaker", "manual"),
                item.get("market", "h2h"),
                item["selection"],
                float(item["odds_decimal"]),
            )
            for item in snapshots
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO odds_snapshots
                (match_id, captured_at, source, bookmaker, market, selection, odds_decimal)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def odds_history(self, match_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT match_id, captured_at, source, bookmaker, market, selection, odds_decimal
                FROM odds_snapshots
                WHERE match_id = ?
                ORDER BY captured_at ASC, bookmaker ASC, market ASC, selection ASC
                """,
                (match_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_snapshot_time(self, match_id: str) -> str | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT MAX(captured_at) AS captured_at FROM odds_snapshots WHERE match_id = ?",
                (match_id,),
            ).fetchone()
        return row["captured_at"] if row and row["captured_at"] else None

    def upsert_fixture(self, fixture: dict[str, Any]) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO fixtures
                (match_id, source, competition, stage, home_team, away_team, kickoff, status,
                 home_score, away_score, venue, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(match_id) DO UPDATE SET
                    source=excluded.source,
                    competition=excluded.competition,
                    stage=excluded.stage,
                    home_team=excluded.home_team,
                    away_team=excluded.away_team,
                    kickoff=excluded.kickoff,
                    status=excluded.status,
                    home_score=excluded.home_score,
                    away_score=excluded.away_score,
                    venue=excluded.venue,
                    raw_json=excluded.raw_json
                """,
                (
                    fixture["match_id"],
                    fixture.get("source", "unknown"),
                    fixture.get("competition"),
                    fixture.get("stage"),
                    fixture["home_team"],
                    fixture["away_team"],
                    fixture.get("kickoff"),
                    fixture.get("status", "scheduled"),
                    fixture.get("home_score"),
                    fixture.get("away_score"),
                    fixture.get("venue"),
                    json.dumps(fixture, ensure_ascii=False),
                ),
            )

    def fixtures(self, status: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT match_id, source, competition, stage, home_team, away_team, kickoff, status,
                   home_score, away_score, venue, raw_json
            FROM fixtures
        """
        params: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            params = (status,)
        sql += " ORDER BY kickoff IS NULL, kickoff ASC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        fixtures = []
        for row in rows:
            fixture = dict(row)
            raw_text = fixture.pop("raw_json", None)
            if raw_text:
                try:
                    raw = json.loads(raw_text)
                except json.JSONDecodeError:
                    raw = {}
                for key in ("sporttery_match_num", "selling_pools", "odds_summary"):
                    if key in raw:
                        fixture[key] = raw[key]
            fixtures.append(fixture)
        return fixtures

    def archive_prediction(self, match_id: str, prediction: dict[str, Any]) -> int:
        rows = []
        captured_at = now_iso()
        data_score = int(prediction["data_completeness"]["score"])
        for scenario in prediction["scenarios"]:
            top_score = scenario["top_scores"][0]["score"] if scenario.get("top_scores") else None
            rows.append(
                (
                    match_id,
                    captured_at,
                    scenario["scenario"],
                    float(scenario["probabilities"]["home"]),
                    float(scenario["probabilities"]["draw"]),
                    float(scenario["probabilities"]["away"]),
                    top_score,
                    float(scenario["over_25"]),
                    float(scenario["btts"]),
                    int(scenario["confidence"]),
                    data_score,
                )
            )
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO prediction_snapshots
                (match_id, captured_at, scenario, home_prob, draw_prob, away_prob, top_score,
                 over_25, btts, confidence, data_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def prediction_snapshots(self, match_id: str | None = None) -> list[dict[str, Any]]:
        sql = """
            SELECT id, match_id, captured_at, scenario, home_prob, draw_prob, away_prob,
                   top_score, over_25, btts, confidence, data_score
            FROM prediction_snapshots
        """
        params: tuple[Any, ...] = ()
        if match_id:
            sql += " WHERE match_id = ?"
            params = (match_id,)
        sql += " ORDER BY captured_at DESC, id DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def insert_backtest_results(self, results: list[dict[str, Any]]) -> int:
        if not results:
            return 0
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO backtest_results
                (match_id, evaluated_at, snapshot_id, scenario, actual_score, actual_result, predicted_result,
                 prediction_prob, pre_match_sp, closing_sp, roi, top1_hit, top2_hit, brier_score, log_loss, score_hit, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["match_id"],
                        item["evaluated_at"],
                        item["snapshot_id"],
                        item["scenario"],
                        item.get("actual_score"),
                        item["actual_result"],
                        item["predicted_result"],
                        item.get("prediction_prob"),
                        item.get("pre_match_sp"),
                        item.get("closing_sp"),
                        item.get("roi"),
                        int(item["top1_hit"]),
                        int(item["top2_hit"]),
                        float(item["brier_score"]),
                        float(item["log_loss"]),
                        int(item["score_hit"]),
                        item.get("notes"),
                    )
                    for item in results
                ],
            )
        return len(results)

    def backtest_results(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, match_id, evaluated_at, snapshot_id, scenario, actual_score, actual_result,
                       predicted_result, prediction_prob, pre_match_sp, closing_sp, roi,
                       top1_hit, top2_hit, brier_score, log_loss, score_hit, notes
                FROM backtest_results
                ORDER BY evaluated_at DESC, id DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]
