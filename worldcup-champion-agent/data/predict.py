from __future__ import annotations

from data.models import Team


def predict(t1: Team, t2: Team) -> tuple[int, int]:
    base_home = 1.2
    base_away = 1.0
    scale = 0.05

    attack_diff = t1.get_attack() - t2.get_defensive()
    home_expected = max(0, round(base_home + attack_diff * scale))

    attack_diff2 = t2.get_attack() - t1.get_defensive()
    away_expected = max(0, round(base_away + attack_diff2 * scale))

    return int(home_expected), int(away_expected)

