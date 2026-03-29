from __future__ import annotations

import math

from app.services.elofit import EloDatabase


_Z_VALUE_95 = 1.959963984540054


def summarize_match(wins: int, draws: int, losses: int) -> dict[str, float | int | None]:
    games = wins + draws + losses
    if games <= 0:
        return {
            "games": 0,
            "score_percent": None,
            "elo": None,
            "elo_stderr": None,
            "elo_lower": None,
            "elo_upper": None,
        }

    # Match Elo should use the same logistic model as the leaderboard fit.
    database = EloDatabase(engines={}, matchups=[])
    database.add_engine("left")
    database.add_engine("right")
    database.add_matchup("left", "right", float(wins), float(losses), float(draws))

    result = database.fit_elo_values(apply=False)
    left = result.estimates["left"]
    right = result.estimates["right"]
    elo = float(result.elos["left"] - result.elos["right"])
    elo_stderr = math.sqrt(max(0.0, (left.stderr * left.stderr) + (right.stderr * right.stderr)))
    score_percent = 100.0 * (wins + 0.5 * draws) / games

    return {
        "games": games,
        "score_percent": score_percent,
        "elo": elo,
        "elo_stderr": elo_stderr,
        "elo_lower": elo - (_Z_VALUE_95 * elo_stderr),
        "elo_upper": elo + (_Z_VALUE_95 * elo_stderr),
        "nll": result.stats.nll,
        "scale": result.stats.scale,
    }
