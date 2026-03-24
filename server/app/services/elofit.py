from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Iterable

import numpy as np
from scipy.optimize import minimize


UNKNOWN_ELO: float | None = None

LN10 = math.log(10.0)
DEFAULT_SCALE = 400.0
SCALE_MIN = 50.0
SCALE_MAX = 2000.0
ALT_ROUNDS = 8
PROB_EPS = 1e-12
Z_VALUE_95 = 1.959963984540054


@dataclass
class Engine:
    name: str
    elo: float | None = UNKNOWN_ELO
    fixed: bool = False

    def is_fixed(self) -> bool:
        return self.fixed


@dataclass(frozen=True)
class MatchUp:
    a: str
    b: str
    wins_a: float
    wins_b: float
    draws: float

    def n_games(self) -> float:
        return float(self.wins_a + self.wins_b + self.draws)

    def score_a(self) -> float:
        return float(self.wins_a + 0.5 * self.draws)

    def p_hat(self) -> float:
        n = self.n_games()
        if n <= 0:
            raise ValueError("MatchUp requires at least one game.")
        return self.score_a() / n


class EloSolver(Enum):
    LBFGS_B = "lbfgs_b"
    CG = "cg"


@dataclass
class EloConfig:
    scale: float | None = None
    max_iter_E: int = 60
    tol_E: float = 1e-8
    max_iter_beta: int = 40
    tol_beta: float = 1e-12
    solver: EloSolver = EloSolver.LBFGS_B
    verbose: bool = False


@dataclass
class EloDatabase:
    engines: Dict[str, Engine]
    matchups: list[MatchUp]
    config: EloConfig = field(default_factory=EloConfig)

    def add_engine(self, name: str, *, fixed: bool = False, elo: float | None = UNKNOWN_ELO) -> None:
        if name in self.engines:
            raise ValueError(f"Engine '{name}' already exists.")
        if fixed and elo is None:
            raise ValueError("Fixed engines must have a known Elo.")
        self.engines[name] = Engine(name=name, fixed=fixed, elo=elo)

    def add_matchup(self, a: str, b: str, wins_a: float, wins_b: float, draws: float) -> None:
        self.matchups.append(MatchUp(a=a, b=b, wins_a=wins_a, wins_b=wins_b, draws=draws))

    def fixed_engines(self) -> list[Engine]:
        return [engine for engine in self.engines.values() if engine.is_fixed()]

    def fixed_count(self) -> int:
        return len(self.fixed_engines())

    def fit_scale(self) -> bool:
        return self.fixed_count() >= 2

    def effective_fixed_scale(self) -> float:
        if self.config.scale is None:
            return DEFAULT_SCALE
        return float(self.config.scale)

    def validate(self) -> None:
        _validate_unique_engine_names(self.engines.values())
        _validate_matchups_reference_known_engines(self.matchups, set(self.engines.keys()))
        _validate_fixed_engines_distinct_values(self.engines.values())

        if self.config.scale is not None and self.config.scale <= 0:
            raise ValueError("config.scale must be > 0 if provided.")
        if not isinstance(self.config.solver, EloSolver):
            raise ValueError("config.solver must be an EloSolver.")

        fixed_count = self.fixed_count()
        if fixed_count >= 2 and self.config.scale is not None:
            raise ValueError("With >=2 fixed engines the scale must be fitted, so config.scale must be None.")
        if self.config.scale is not None and fixed_count != 1:
            raise ValueError("config.scale may only be set when exactly one engine is fixed.")

    def fit_elo_values(self, *, apply: bool = True) -> "EloFitResult":
        result = fit_elo_mle(self)
        if apply:
            for name, elo in result.elos.items():
                if not self.engines[name].fixed:
                    self.engines[name].elo = float(elo)
        return result


@dataclass(frozen=True)
class EloSolveStats:
    started_at: datetime
    finished_at: datetime
    iters: int
    nll: float
    scale: float
    beta: float
    elo_move_abs_sum: float
    elo_move_abs_mean: float
    unknown_elo_count: int
    unknown_elo_abs_sum: float
    elapsed_time_starting_fit: float
    elapsed_time_solver: float
    elapsed_time_total: float


@dataclass(frozen=True)
class EloFitResult:
    elos: Dict[str, float]
    estimates: Dict[str, "EloEstimate"]
    stats: EloSolveStats


@dataclass(frozen=True)
class EloEstimate:
    elo: float
    stderr: float
    ci_lower: float
    ci_upper: float


@dataclass(frozen=True)
class _PreparedMatchups:
    ia: np.ndarray
    ib: np.ndarray
    n_games: np.ndarray
    p_hat: np.ndarray


def _validate_unique_engine_names(engines: Iterable[Engine]) -> None:
    names = [engine.name for engine in engines]
    if len(names) != len(set(names)):
        raise ValueError("Engine names must be unique.")


def _validate_matchups_reference_known_engines(matchups: Iterable[MatchUp], known: set[str]) -> None:
    for matchup in matchups:
        if matchup.a not in known:
            raise ValueError(f"Unknown engine '{matchup.a}'.")
        if matchup.b not in known:
            raise ValueError(f"Unknown engine '{matchup.b}'.")
        if matchup.a == matchup.b:
            raise ValueError("MatchUp requires distinct engines.")
        if matchup.n_games() <= 0:
            raise ValueError("MatchUp requires at least one game.")
        if matchup.wins_a < 0 or matchup.wins_b < 0 or matchup.draws < 0:
            raise ValueError("MatchUp counts must be non-negative.")


def _validate_fixed_engines_distinct_values(engines: Iterable[Engine]) -> None:
    fixed_values: list[float] = []
    for engine in engines:
        if engine.fixed:
            if engine.elo is None:
                raise ValueError("Fixed engines must have a known Elo.")
            fixed_values.append(float(engine.elo))
    if len(fixed_values) >= 2 and len(fixed_values) != len(set(fixed_values)):
        raise ValueError("Fixed anchors must have distinct Elo values.")


def _clamp_prob(probability: float, eps: float = PROB_EPS) -> float:
    if probability < eps:
        return eps
    if probability > 1.0 - eps:
        return 1.0 - eps
    return probability


def _build_index(database: EloDatabase) -> tuple[list[str], dict[str, int]]:
    names = sorted(database.engines.keys())
    return names, {name: index for index, name in enumerate(names)}


def _initial_vector(database: EloDatabase, names: list[str]) -> np.ndarray:
    initial = np.zeros(len(names), dtype=np.float64)
    for index, name in enumerate(names):
        engine = database.engines[name]
        initial[index] = float(engine.elo) if engine.elo is not None else 0.0
    return initial


def _estimate_unknown_elos(database: EloDatabase) -> tuple[int, float]:
    unknown = [name for name, engine in database.engines.items() if engine.elo is None]
    if not unknown:
        return 0, 0.0

    scale = DEFAULT_SCALE if database.fit_scale() else database.effective_fixed_scale()
    remaining = set(unknown)
    while remaining:
        targets: dict[str, list[float]] = {name: [] for name in remaining}
        for matchup in database.matchups:
            elo_a = database.engines[matchup.a].elo
            elo_b = database.engines[matchup.b].elo
            if elo_a is None and elo_b is None:
                continue
            phat = _clamp_prob(matchup.p_hat())
            diff = scale * math.log10(phat / (1.0 - phat))
            if elo_a is None and elo_b is not None and matchup.a in remaining:
                targets[matchup.a].append(float(elo_b) + diff)
            if elo_b is None and elo_a is not None and matchup.b in remaining:
                targets[matchup.b].append(float(elo_a) - diff)

        updated = 0
        for name in list(remaining):
            if not targets[name]:
                continue
            database.engines[name].elo = sum(targets[name]) / len(targets[name])
            remaining.remove(name)
            updated += 1
        if updated == 0:
            break

    for name in remaining:
        database.engines[name].elo = 0.0

    move_abs_sum = 0.0
    for name in unknown:
        value = database.engines[name].elo
        move_abs_sum += abs(float(value)) if value is not None else 0.0
    return len(unknown), move_abs_sum


def _fixed_mask_and_values(database: EloDatabase, names: list[str]) -> tuple[np.ndarray, np.ndarray]:
    fixed_mask = np.zeros(len(names), dtype=bool)
    fixed_values = np.zeros(len(names), dtype=np.float64)
    for index, name in enumerate(names):
        engine = database.engines[name]
        fixed_mask[index] = bool(engine.fixed)
        fixed_values[index] = float(engine.elo) if engine.fixed and engine.elo is not None else 0.0
    return fixed_mask, fixed_values


def _prepare_matchups(database: EloDatabase, lookup: dict[str, int]) -> _PreparedMatchups:
    count = len(database.matchups)
    ia = np.empty(count, dtype=np.int32)
    ib = np.empty(count, dtype=np.int32)
    n_games = np.empty(count, dtype=np.float64)
    p_hat = np.empty(count, dtype=np.float64)
    for index, matchup in enumerate(database.matchups):
        ia[index] = lookup[matchup.a]
        ib[index] = lookup[matchup.b]
        n_games[index] = float(matchup.n_games())
        p_hat[index] = float(matchup.p_hat())
    return _PreparedMatchups(ia=ia, ib=ib, n_games=n_games, p_hat=p_hat)


def _sigmoid_vector(values: np.ndarray) -> np.ndarray:
    output = np.empty_like(values)
    positive = values >= 0.0
    negative = ~positive
    output[positive] = 1.0 / (1.0 + np.exp(-values[positive]))
    exp_values = np.exp(values[negative])
    output[negative] = exp_values / (1.0 + exp_values)
    return output


def _clamp_prob_vector(values: np.ndarray) -> np.ndarray:
    return np.clip(values, PROB_EPS, 1.0 - PROB_EPS)


def _nll_grad_prepared(elos: np.ndarray, beta: float, data: _PreparedMatchups) -> tuple[float, np.ndarray]:
    diff = elos[data.ia] - elos[data.ib]
    probabilities = _clamp_prob_vector(_sigmoid_vector(beta * diff))
    nll = np.sum(data.n_games * (-(data.p_hat * np.log(probabilities) + (1.0 - data.p_hat) * np.log(1.0 - probabilities))))
    terms = beta * data.n_games * (probabilities - data.p_hat)
    gradient = np.zeros_like(elos)
    np.add.at(gradient, data.ia, terms)
    np.add.at(gradient, data.ib, -terms)
    return float(nll), gradient


def _nll_only_prepared(elos: np.ndarray, beta: float, data: _PreparedMatchups) -> float:
    diff = elos[data.ia] - elos[data.ib]
    probabilities = _clamp_prob_vector(_sigmoid_vector(beta * diff))
    nll = np.sum(data.n_games * (-(data.p_hat * np.log(probabilities) + (1.0 - data.p_hat) * np.log(1.0 - probabilities))))
    return float(nll)


def _elo_hessian_prepared(elos: np.ndarray, beta: float, data: _PreparedMatchups) -> np.ndarray:
    diff = elos[data.ia] - elos[data.ib]
    probabilities = _clamp_prob_vector(_sigmoid_vector(beta * diff))
    weights = data.n_games * (beta * beta) * probabilities * (1.0 - probabilities)
    hessian = np.zeros((elos.size, elos.size), dtype=np.float64)
    np.add.at(hessian, (data.ia, data.ia), weights)
    np.add.at(hessian, (data.ib, data.ib), weights)
    np.add.at(hessian, (data.ia, data.ib), -weights)
    np.add.at(hessian, (data.ib, data.ia), -weights)
    return hessian


def _elo_beta_cross_hessian_prepared(elos: np.ndarray, beta: float, data: _PreparedMatchups) -> tuple[np.ndarray, float]:
    diff = elos[data.ia] - elos[data.ib]
    probabilities = _clamp_prob_vector(_sigmoid_vector(beta * diff))
    cross_terms = data.n_games * ((probabilities - data.p_hat) + (beta * probabilities * (1.0 - probabilities) * diff))
    cross = np.zeros(elos.size, dtype=np.float64)
    np.add.at(cross, data.ia, cross_terms)
    np.add.at(cross, data.ib, -cross_terms)
    beta_beta = float(np.sum(data.n_games * probabilities * (1.0 - probabilities) * diff * diff))
    return cross, beta_beta


def _apply_min_zero(elos: np.ndarray) -> np.ndarray:
    if elos.size == 0:
        return elos
    return elos - np.min(elos)


def _connected_components(data: _PreparedMatchups, engine_count: int) -> list[list[int]]:
    neighbors: list[set[int]] = [set() for _ in range(engine_count)]
    for left, right in zip(data.ia.tolist(), data.ib.tolist()):
        neighbors[left].add(right)
        neighbors[right].add(left)

    seen: set[int] = set()
    components: list[list[int]] = []
    for start in range(engine_count):
        if start in seen:
            continue
        stack = [start]
        component: list[int] = []
        seen.add(start)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbor in neighbors[current]:
                if neighbor in seen:
                    continue
                seen.add(neighbor)
                stack.append(neighbor)
        components.append(sorted(component))
    return components


def _confidence_intervals_from_covariance(
    database: EloDatabase,
    names: list[str],
    elos: np.ndarray,
    beta: float,
    data: _PreparedMatchups,
    fixed_mask: np.ndarray,
) -> dict[str, EloEstimate]:
    estimates: dict[str, EloEstimate] = {}
    if elos.size == 0:
        return estimates

    pseudo_anchor_indices: set[int] = set()
    components = _connected_components(data, elos.size)
    for component in components:
        if any(fixed_mask[index] for index in component):
            continue
        pseudo_anchor_indices.add(min(component, key=lambda index: (float(elos[index]), index)))

    free_indices = np.array(
        [index for index in range(elos.size) if not fixed_mask[index] and index not in pseudo_anchor_indices],
        dtype=np.int32,
    )

    for index, name in enumerate(names):
        if fixed_mask[index] or index in pseudo_anchor_indices:
            value = float(elos[index])
            estimates[name] = EloEstimate(elo=value, stderr=0.0, ci_lower=value, ci_upper=value)

    if free_indices.size == 0:
        for index, name in enumerate(names):
            if name not in estimates:
                value = float(elos[index])
                estimates[name] = EloEstimate(elo=value, stderr=0.0, ci_lower=value, ci_upper=value)
        return estimates

    elo_hessian = _elo_hessian_prepared(elos, beta, data)
    if database.fit_scale():
        cross, beta_beta = _elo_beta_cross_hessian_prepared(elos, beta, data)
        hessian = np.zeros((free_indices.size + 1, free_indices.size + 1), dtype=np.float64)
        hessian[:-1, :-1] = elo_hessian[np.ix_(free_indices, free_indices)]
        hessian[:-1, -1] = cross[free_indices]
        hessian[-1, :-1] = cross[free_indices]
        hessian[-1, -1] = beta_beta
        covariance = np.linalg.pinv(hessian)
        elo_covariance = covariance[:-1, :-1]
    else:
        hessian = elo_hessian[np.ix_(free_indices, free_indices)]
        elo_covariance = np.linalg.pinv(hessian)

    variances = np.maximum(0.0, np.diag(elo_covariance))
    for local_index, global_index in enumerate(free_indices):
        value = float(elos[global_index])
        stderr = float(math.sqrt(float(variances[local_index])))
        estimates[names[global_index]] = EloEstimate(
            elo=value,
            stderr=stderr,
            ci_lower=value - (Z_VALUE_95 * stderr),
            ci_upper=value + (Z_VALUE_95 * stderr),
        )

    for index, name in enumerate(names):
        if name in estimates:
            continue
        value = float(elos[index])
        estimates[name] = EloEstimate(elo=value, stderr=0.0, ci_lower=value, ci_upper=value)
    return estimates


def _minimize_solve_elos(
    database: EloDatabase,
    initial_elos: np.ndarray,
    beta: float,
    data: _PreparedMatchups,
    fixed_mask: np.ndarray,
    fixed_values: np.ndarray,
    method: str,
) -> tuple[np.ndarray, float, int]:
    elos = np.array(initial_elos, dtype=np.float64, copy=True)
    elos[fixed_mask] = fixed_values[fixed_mask]
    free_indices = np.flatnonzero(~fixed_mask)
    if free_indices.size == 0:
        return elos, _nll_only_prepared(elos, beta, data), 0

    start_free = elos[free_indices].copy()

    def pack_full(free_values: np.ndarray) -> np.ndarray:
        full = elos.copy()
        full[free_indices] = free_values
        full[fixed_mask] = fixed_values[fixed_mask]
        return full

    def objective_and_gradient(free_values: np.ndarray) -> tuple[float, np.ndarray]:
        full = pack_full(free_values)
        nll, gradient = _nll_grad_prepared(full, beta, data)
        return nll, gradient[free_indices]

    result = minimize(
        objective_and_gradient,
        start_free,
        method=method,
        jac=True,
        options={"maxiter": database.config.max_iter_E, "gtol": database.config.tol_E},
    )
    solved = pack_full(np.asarray(result.x, dtype=np.float64))
    solved[fixed_mask] = fixed_values[fixed_mask]
    return solved, float(result.fun), int(result.nit or 0)


def _beta_grad_hess_prepared(elos: np.ndarray, beta: float, data: _PreparedMatchups) -> tuple[float, float]:
    diff = elos[data.ia] - elos[data.ib]
    probabilities = _clamp_prob_vector(_sigmoid_vector(beta * diff))
    first = np.sum(data.n_games * (probabilities - data.p_hat) * diff)
    second = np.sum(data.n_games * probabilities * (1.0 - probabilities) * diff * diff)
    return float(first), float(second)


def _newton_solve_beta(
    database: EloDatabase,
    elos: np.ndarray,
    beta0: float,
    data: _PreparedMatchups,
    beta_min: float,
    beta_max: float,
) -> tuple[float, int]:
    beta = min(max(beta0, beta_min), beta_max)
    for iteration in range(1, database.config.max_iter_beta + 1):
        first, second = _beta_grad_hess_prepared(elos, beta, data)
        if abs(second) < 1e-30:
            return beta, iteration
        beta_new = min(max(beta - (first / second), beta_min), beta_max)
        if abs(beta_new - beta) < database.config.tol_beta * max(1.0, abs(beta)):
            return beta_new, iteration
        beta = beta_new
    return beta, database.config.max_iter_beta


def fit_elo_mle(database: EloDatabase) -> EloFitResult:
    database.validate()

    start_clock = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    baseline = {name: 0.0 if engine.elo is None else float(engine.elo) for name, engine in database.engines.items()}

    unknown_count, unknown_abs_sum = _estimate_unknown_elos(database)
    names, lookup = _build_index(database)
    fixed_mask, fixed_values = _fixed_mask_and_values(database, names)
    elos = _initial_vector(database, names)
    data = _prepare_matchups(database, lookup)

    if database.config.solver == EloSolver.LBFGS_B:
        method = "L-BFGS-B"
    elif database.config.solver == EloSolver.CG:
        method = "CG"
    else:
        raise ValueError(f"Unsupported solver {database.config.solver}.")

    total_iters = 0
    solver_start = time.perf_counter()
    solver_end = solver_start

    if not database.fit_scale():
        scale = database.effective_fixed_scale()
        beta = LN10 / float(scale)
        elos, nll, iter_elos = _minimize_solve_elos(database, elos, beta, data, fixed_mask, fixed_values, method)
        solver_end = time.perf_counter()
        total_iters += iter_elos
        if database.fixed_count() == 0:
            elos = _apply_min_zero(elos)
            nll = _nll_only_prepared(elos, beta, data)
    else:
        beta = LN10 / DEFAULT_SCALE
        beta_min = LN10 / SCALE_MAX
        beta_max = LN10 / SCALE_MIN
        nll = float("inf")
        for _ in range(ALT_ROUNDS):
            elos, _, iter_elos = _minimize_solve_elos(database, elos, beta, data, fixed_mask, fixed_values, method)
            total_iters += iter_elos
            beta_new, iter_beta = _newton_solve_beta(database, elos, beta, data, beta_min, beta_max)
            total_iters += iter_beta
            nll = _nll_only_prepared(elos, beta_new, data)
            if abs(beta_new - beta) < 1e-10 * max(1.0, abs(beta)):
                beta = beta_new
                break
            beta = beta_new
        scale = LN10 / beta
        solver_end = time.perf_counter()

    move_abs_sum = 0.0
    move_count = 0
    for index, name in enumerate(names):
        if fixed_mask[index]:
            continue
        move_abs_sum += abs(float(elos[index]) - baseline[name])
        move_count += 1

    finished_at = datetime.now(timezone.utc)
    stats = EloSolveStats(
        started_at=started_at,
        finished_at=finished_at,
        iters=int(total_iters),
        nll=float(nll),
        scale=float(scale),
        beta=float(beta),
        elo_move_abs_sum=float(move_abs_sum),
        elo_move_abs_mean=float(move_abs_sum / move_count) if move_count else 0.0,
        unknown_elo_count=int(unknown_count),
        unknown_elo_abs_sum=float(unknown_abs_sum),
        elapsed_time_starting_fit=0.0,
        elapsed_time_solver=float(solver_end - solver_start),
        elapsed_time_total=float(time.perf_counter() - start_clock),
    )
    estimates = _confidence_intervals_from_covariance(database, names, elos, beta, data, fixed_mask)
    return EloFitResult(
        elos={name: float(elos[index]) for index, name in enumerate(names)},
        estimates=estimates,
        stats=stats,
    )
