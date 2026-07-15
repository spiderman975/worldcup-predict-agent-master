from fastapi import HTTPException

from app.api import team_router
from app.services.cache_service import cache_service


def test_team_detail_returns_members(monkeypatch) -> None:
    cache_service._memory.clear()

    def fake_team_detail(team_id: str) -> dict:
        assert team_id == "FRANCE"
        return {
            "team_id": "FRANCE",
            "name": "France",
            "group": "I",
            "fifa_rank": 2,
            "attack_score": 0.9,
            "defense_score": 0.8,
            "recent_form": 0.7,
            "starting_lineup": ["Kylian Mbappe"],
            "members": [
                {
                    "name": "Kylian Mbappe",
                    "attack": 92,
                    "defensive": 50,
                    "injured": False,
                    "injury_description": "",
                    "is_starting": True,
                }
            ],
        }

    monkeypatch.setattr(team_router.data_scout_service, "team_detail", fake_team_detail)
    payload = team_router.get_team("FRANCE")
    assert payload["members"]
    member = payload["members"][0]
    assert {"name", "attack", "defensive", "injured", "is_starting"} <= set(member)


def test_team_detail_returns_404(monkeypatch) -> None:
    cache_service._memory.clear()
    monkeypatch.setattr(team_router.data_scout_service, "team_detail", lambda team_id: None)

    try:
        team_router.get_team("NOPE")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("Expected missing team to raise HTTPException")
