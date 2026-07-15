from app.api import match_router, ops_router


def test_ops_live_sync_status_route(monkeypatch) -> None:
    monkeypatch.setattr(ops_router.live_score_sync_service, "status", lambda: {"status": "success", "enabled": True})
    assert ops_router.live_sync_status()["status"] == "success"


def test_matches_fresh_bypasses_cache(monkeypatch) -> None:
    called = {"list_schedule": 0, "remember": 0}

    def fake_list_schedule():
        called["list_schedule"] += 1
        return [{"match_id": "s5_france_spain", "stage": "semi"}]

    def fake_remember(*args, **kwargs):
        called["remember"] += 1
        return []

    monkeypatch.setattr(match_router, "list_schedule", fake_list_schedule)
    monkeypatch.setattr(match_router.cache_service, "remember", fake_remember)

    result = match_router.list_matches(fresh=True)

    assert result == [{"match_id": "s5_france_spain", "stage": "semi"}]
    assert called["list_schedule"] == 1
    assert called["remember"] == 0


def test_schedule_fresh_bypasses_cache(monkeypatch) -> None:
    called = {"list_schedule": 0, "remember": 0}

    def fake_list_schedule():
        called["list_schedule"] += 1
        return [{"match_id": "s5_france_spain", "stage": "semi", "match_date": "2026-07-15"}]

    def fake_remember(*args, **kwargs):
        called["remember"] += 1
        return {}

    monkeypatch.setattr(match_router, "list_schedule", fake_list_schedule)
    monkeypatch.setattr(match_router.cache_service, "remember", fake_remember)

    result = match_router.get_schedule(fresh=True)

    assert result["dates"] == [{"date": "2026-07-15", "matches": [{"match_id": "s5_france_spain", "stage": "semi", "match_date": "2026-07-15"}]}]
    assert called["list_schedule"] == 1
    assert called["remember"] == 0
