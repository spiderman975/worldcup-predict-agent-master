from __future__ import annotations

import json
import asyncio
import uuid
from pathlib import Path
from datetime import datetime

from app.services.live_score_sync_service import ExternalMatch, LiveScoreSyncService
from app.services.match_prediction_service import _prediction_summary, match_display_status


class Row(dict):
    def keys(self):
        return super().keys()


def row(played_at: str, *, is_real: int = 0, home_score: int = -1, away_score: int = -1, status: str = "") -> Row:
    return Row(
        played_at=played_at,
        is_real=is_real,
        home_score=home_score,
        away_score=away_score,
        status=status,
    )


def test_match_display_status_by_beijing_time() -> None:
    now = datetime(2026, 7, 16, 12, 0, 0)
    assert match_display_status(row("2026-07-18T10:00:00Z"), now) == "scheduled"
    assert match_display_status(row("2026-07-16T03:00:00Z"), now) == "live"
    assert match_display_status(row("2026-07-15T10:00:00Z"), now) == "result_pending"
    assert match_display_status(row("2026-07-18T10:00:00Z", is_real=1, home_score=2, away_score=1), now) == "finished"


def test_live_sync_updates_local_match_id_and_not_external_id(monkeypatch) -> None:
    db = _prepare_db(monkeypatch)
    called = {"count": 0}
    monkeypatch.setattr("app.services.live_score_sync_service.cache_service.invalidate_matches", lambda match_id=None: called.__setitem__("count", called["count"] + 1))

    service = LiveScoreSyncService()
    result = service._apply_external_matches([
        ExternalMatch("123456", 5, "semi", "France", "Spain", 2, 1, True, "2026-07-14T19:00:00Z", "FINISHED")
    ])

    with db.get_connection() as connection:
        rows = connection.execute("SELECT match_id, home_score, away_score, is_real FROM matches ORDER BY match_id").fetchall()
    assert result["updated_matches"] == 1
    assert [row["match_id"] for row in rows] == ["s5_france_spain"]
    assert rows[0]["home_score"] == 2
    assert rows[0]["away_score"] == 1
    assert rows[0]["is_real"] == 1
    assert called["count"] == 1


def test_live_sync_swaps_scores_when_home_away_reversed(monkeypatch) -> None:
    db = _prepare_db(monkeypatch)
    monkeypatch.setattr("app.services.live_score_sync_service.cache_service.invalidate_matches", lambda match_id=None: None)
    service = LiveScoreSyncService()

    service._apply_external_matches([
        ExternalMatch("123456", 5, "semi", "Spain", "France", 3, 4, True, "2026-07-14T19:00:00Z", "FINISHED")
    ])

    with db.get_connection() as connection:
        stored = connection.execute("SELECT home_score, away_score FROM matches WHERE match_id = 's5_france_spain'").fetchone()
    assert stored["home_score"] == 4
    assert stored["away_score"] == 3


def test_live_sync_ambiguous_candidates_are_not_updated(monkeypatch) -> None:
    db = _prepare_db(monkeypatch, duplicate=True)
    monkeypatch.setattr("app.services.live_score_sync_service.cache_service.invalidate_matches", lambda match_id=None: None)
    service = LiveScoreSyncService()

    result = service._apply_external_matches([
        ExternalMatch("123456", 5, "semi", "France", "Spain", 2, 1, True, None, "FINISHED")
    ])

    with db.get_connection() as connection:
        changed = connection.execute("SELECT COUNT(*) FROM matches WHERE is_real = 1").fetchone()[0]
    assert result["updated_matches"] == 0
    assert result["ambiguous_matches"]
    assert changed == 0


def test_live_sync_missing_api_key_does_not_crash() -> None:
    service = LiveScoreSyncService()
    service.settings.football_data_api_key = None
    result = asyncio.run(service.sync_once(force=True))
    assert result["success"] is False
    assert result["status"] == "missing_api_key"


def test_prediction_summary_omits_agent_trace() -> None:
    record = {
        "mode": "historical",
        "created_at": "2026-07-16T12:00:00",
        "agent_trace": ["large"],
        "prediction": {
            "predicted_home_score": 2,
            "predicted_away_score": 1,
            "home_win_prob": 0.5,
            "draw_prob": 0.25,
            "away_win_prob": 0.25,
            "explanation": "ok",
        },
    }
    summary = _prediction_summary(record)
    assert summary
    assert "agent_trace" not in summary
    assert summary["predicted_home_score"] == 2


def _prepare_db(monkeypatch, *, duplicate: bool = False):
    from data import database as db

    db_dir = Path(".agent_data")
    db_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(db, "DB_PATH", db_dir / f"test_live_sync_{uuid.uuid4().hex}.db")
    db.init_db()
    with db.get_connection() as connection:
        for name in ("France", "Spain"):
            connection.execute(
                'INSERT INTO teams (name, "group", attack_team, defensive_team, streak, starting_lineup, fifa_ranking) VALUES (?, "A", 1, 1, 0, ?, 1)',
                (name, json.dumps([])),
            )
        connection.execute(
            """
            INSERT INTO matches (match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at, status)
            VALUES ('s5_france_spain', 5, 'France', 'Spain', -1, -1, 0, '2026-07-14T19:00:00Z', '')
            """
        )
        if duplicate:
            connection.execute(
                """
                INSERT INTO matches (match_id, stage, home_team, away_team, home_score, away_score, is_real, played_at, status)
                VALUES ('another_france_spain', 5, 'France', 'Spain', -1, -1, 0, '2026-07-14T19:30:00Z', '')
                """
            )
    return db
