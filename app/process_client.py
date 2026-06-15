from __future__ import annotations

from copy import deepcopy
from typing import Any

from .scrapers.public_sources import PublicSourceError, scrape_match_process_source, update_health
from .source_registry import load_source_health, load_sources, save_source_health


PROCESS_SOURCE_TYPES = {"msn_match_process", "match_process_html_regex"}


def fetch_match_process(match: dict[str, Any]) -> dict[str, Any] | None:
    sources = sorted(load_sources(), key=lambda item: item.get("priority", 50))
    health = load_source_health()
    for source in sources:
        if not source.get("enabled") or source.get("type") not in PROCESS_SOURCE_TYPES:
            continue
        try:
            payload = scrape_match_process_source(source, match)
        except (PublicSourceError, OSError, ValueError, KeyError, IndexError) as exc:
            update_health(health, source, ok=False, error=str(exc))
            continue
        update_health(health, source, ok=True, rows=count_process_metrics(payload))
        save_source_health(health)
        return payload
    save_source_health(health)
    return None


def count_process_metrics(payload: dict[str, Any]) -> int:
    stats = payload.get("stats") or {}
    return sum(len(values or {}) for values in stats.values() if isinstance(values, dict))


def merge_match_process(match: dict[str, Any], process_payload: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    if not process_payload:
        return match, False
    enriched = deepcopy(match)
    stats = process_payload.get("stats") or {}
    if not stats:
        return match, False
    enriched["match_process_stats"] = stats
    enriched["match_process_source"] = process_payload.get("source")
    enriched["match_process_captured_at"] = process_payload.get("captured_at")
    notes = list(enriched.get("process_notes", [])) if isinstance(enriched.get("process_notes"), list) else []
    note = process_payload.get("notes")
    if note and note not in notes:
        notes.append(note)
    if notes:
        enriched["process_notes"] = notes
    return enriched, enriched != match
