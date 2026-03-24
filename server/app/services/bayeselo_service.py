from __future__ import annotations

import math
import numpy as np


_Z_VALUE_95 = 1.959963984540054


def _probabilities(elo: float, drawelo: float) -> tuple[float, float, float]:
    win = 1.0 / (1.0 + 10 ** ((drawelo - elo) / 400.0))
    loss = 1.0 / (1.0 + 10 ** ((drawelo + elo) / 400.0))
    draw = max(1e-12, 1.0 - win - loss)
    return max(1e-12, win), draw, max(1e-12, loss)


def _log_likelihood(wins: int, draws: int, losses: int, elo: float, drawelo: float) -> float:
    win_p, draw_p, loss_p = _probabilities(elo, drawelo)
    return wins * math.log(win_p) + draws * math.log(draw_p) + losses * math.log(loss_p)


def _negative_log_likelihood(wins: int, draws: int, losses: int, elo: float, drawelo: float) -> float:
    return -_log_likelihood(wins, draws, losses, elo, drawelo)


def _grid_search(
    wins: int,
    draws: int,
    losses: int,
    elo_center: float,
    drawelo_center: float,
    elo_span: float,
    drawelo_span: float,
    steps: int = 17,
) -> tuple[float, float, float]:
    best = (float("-inf"), elo_center, drawelo_center)
    for elo_index in range(steps):
        elo = elo_center - elo_span + (2.0 * elo_span * elo_index / max(1, steps - 1))
        for draw_index in range(steps):
            drawelo = max(0.0, drawelo_center - drawelo_span + (2.0 * drawelo_span * draw_index / max(1, steps - 1)))
            ll = _log_likelihood(wins, draws, losses, elo, drawelo)
            if ll > best[0]:
                best = (ll, elo, drawelo)
    return best


def _maximize(wins: int, draws: int, losses: int) -> tuple[float, float, float]:
    score = (wins + 0.5 * draws) / max(1, wins + draws + losses)
    clipped_score = min(max(score, 1e-6), 1.0 - 1e-6)
    elo = 400.0 * math.log10(clipped_score / (1.0 - clipped_score))
    draw_rate = draws / max(1, wins + draws + losses)
    drawelo = min(800.0, max(0.0, 400.0 * math.log10((1.0 / max(1e-6, 1.0 - draw_rate)) - 1.0))) if draw_rate < 0.999999 else 800.0
    best_ll = float("-inf")
    for span in (500.0, 200.0, 80.0, 30.0, 12.0, 5.0):
        best_ll, elo, drawelo = _grid_search(wins, draws, losses, elo, drawelo, span, span, steps=17)
    return elo, drawelo, best_ll


def _observed_information(wins: int, draws: int, losses: int, elo: float, drawelo: float) -> np.ndarray:
    step_elo = max(1.0, abs(elo) * 0.01)
    step_drawelo = max(1.0, abs(drawelo) * 0.01 if drawelo else 1.0)

    def f(elo_value: float, drawelo_value: float) -> float:
        return _negative_log_likelihood(wins, draws, losses, elo_value, max(0.0, drawelo_value))

    center = f(elo, drawelo)
    dxx = (f(elo + step_elo, drawelo) - (2.0 * center) + f(elo - step_elo, drawelo)) / (step_elo * step_elo)
    dyy = (f(elo, drawelo + step_drawelo) - (2.0 * center) + f(elo, drawelo - step_drawelo)) / (step_drawelo * step_drawelo)
    dxy = (
        f(elo + step_elo, drawelo + step_drawelo)
        - f(elo + step_elo, drawelo - step_drawelo)
        - f(elo - step_elo, drawelo + step_drawelo)
        + f(elo - step_elo, drawelo - step_drawelo)
    ) / (4.0 * step_elo * step_drawelo)
    return np.array([[dxx, dxy], [dxy, dyy]], dtype=np.float64)


def summarize_match(wins: int, draws: int, losses: int) -> dict[str, float | int | None]:
    games = wins + draws + losses
    if games <= 0:
        return {
            "games": 0,
            "score_percent": None,
            "elo": None,
            "elo_lower": None,
            "elo_upper": None,
        }

    elo, drawelo, best_ll = _maximize(wins, draws, losses)
    score_percent = 100.0 * (wins + 0.5 * draws) / games
    information = _observed_information(wins, draws, losses, elo, drawelo)
    covariance = np.linalg.pinv(information)
    elo_variance = max(0.0, float(covariance[0, 0]))
    elo_stderr = math.sqrt(elo_variance)
    lower = elo - (_Z_VALUE_95 * elo_stderr)
    upper = elo + (_Z_VALUE_95 * elo_stderr)

    return {
        "games": games,
        "score_percent": score_percent,
        "elo": elo,
        "elo_stderr": elo_stderr,
        "elo_lower": lower,
        "elo_upper": upper,
        "drawelo": drawelo,
        "nll": -best_ll,
    }
