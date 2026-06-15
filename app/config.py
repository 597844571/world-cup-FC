from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
OUTPUTS_DIR = ROOT / "outputs"
WEB_DIR = ROOT / "web"
DB_PATH = DATA_DIR / "odds_snapshots.sqlite"
MATCHES_PATH = DATA_DIR / "matches.json"
SOURCES_PATH = DATA_DIR / "sources.json"
SOURCE_HEALTH_PATH = DATA_DIR / "source_health.json"
STANDINGS_PATH = DATA_DIR / "group_standings.json"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
