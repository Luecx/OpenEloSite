import { Keys } from "./core.js";

function numericValues(values) {
  return values.filter((value) => typeof value === "number" && Number.isFinite(value));
}

function mean(values) {
  if (!values.length) {
    return null;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function ensureEngine(map, name) {
  if (!map.has(name)) {
    map.set(name, {
      name,
      games: 0,
      whiteGames: 0,
      blackGames: 0,
      wins: 0,
      draws: 0,
      losses: 0,
      score: 0,
      plies: 0,
      bookPlies: 0,
      depths: [],
      seldepths: [],
      timeUsed: [],
      nodes: [],
      nps: [],
    });
  }
  return map.get(name);
}

function accumulateResult(stats, result, isWhite) {
  stats.games += 1;
  if (isWhite) {
    stats.whiteGames += 1;
  } else {
    stats.blackGames += 1;
  }
  if (result === "1-0") {
    if (isWhite) {
      stats.wins += 1;
      stats.score += 1;
    } else {
      stats.losses += 1;
    }
    return;
  }
  if (result === "0-1") {
    if (isWhite) {
      stats.losses += 1;
    } else {
      stats.wins += 1;
      stats.score += 1;
    }
    return;
  }
  stats.draws += 1;
  stats.score += 0.5;
}

export function buildInsights(bundle) {
  const { games, dataframe, skippedGames } = bundle;
  const engineStats = new Map();
  let whiteWins = 0;
  let blackWins = 0;
  let draws = 0;
  let totalPlies = 0;

  games.forEach((game) => {
    const whiteName = game.rawHeaders.White || game.headers?.[Keys.NAME]?.w || "White";
    const blackName = game.rawHeaders.Black || game.headers?.[Keys.NAME]?.b || "Black";
    const result = game.rawHeaders.Result || "1/2-1/2";

    totalPlies += game.moves.length;

    if (result === "1-0") {
      whiteWins += 1;
    } else if (result === "0-1") {
      blackWins += 1;
    } else {
      draws += 1;
    }

    accumulateResult(ensureEngine(engineStats, whiteName), result, true);
    accumulateResult(ensureEngine(engineStats, blackName), result, false);
  });

  const names = dataframe.getColumn(Keys.NAME);
  const depths = dataframe.getColumn(Keys.DEPTH);
  const seldepths = dataframe.getColumn(Keys.SELDEPTH);
  const timeUsed = dataframe.getColumn(Keys.TIME_USED);
  const nodes = dataframe.getColumn(Keys.NODES);
  const nps = dataframe.getColumn(Keys.NPS);
  const book = dataframe.getColumn(Keys.BOOK);

  names.forEach((name, index) => {
    if (!name) {
      return;
    }
    const stats = ensureEngine(engineStats, name);
    stats.plies += 1;
    if (book[index]) {
      stats.bookPlies += 1;
    }
    if (Number.isFinite(depths[index])) {
      stats.depths.push(depths[index]);
    }
    if (Number.isFinite(seldepths[index])) {
      stats.seldepths.push(seldepths[index]);
    }
    if (Number.isFinite(timeUsed[index])) {
      stats.timeUsed.push(timeUsed[index]);
    }
    if (Number.isFinite(nodes[index])) {
      stats.nodes.push(nodes[index]);
    }
    if (Number.isFinite(nps[index])) {
      stats.nps.push(nps[index]);
    }
  });

  const engineRows = Array.from(engineStats.values())
    .map((stats) => ({
      name: stats.name,
      games: stats.games,
      whiteGames: stats.whiteGames,
      blackGames: stats.blackGames,
      wins: stats.wins,
      draws: stats.draws,
      losses: stats.losses,
      points: stats.score,
      scorePercent: stats.games ? (stats.score / stats.games) * 100 : null,
      plies: stats.plies,
      avgDepth: mean(numericValues(stats.depths)),
      avgSelDepth: mean(numericValues(stats.seldepths)),
      avgTimeUsed: mean(numericValues(stats.timeUsed)),
      avgNodes: mean(numericValues(stats.nodes)),
      avgNps: mean(numericValues(stats.nps)),
      bookShare: stats.plies ? stats.bookPlies / stats.plies : null,
    }))
    .sort((left, right) => {
      if (right.games !== left.games) {
        return right.games - left.games;
      }
      return right.points - left.points;
    });

  return {
    totalGames: games.length,
    totalPlies,
    skippedGames,
    engineCount: engineRows.length,
    averagePliesPerGame: games.length ? totalPlies / games.length : null,
    resultBreakdown: {
      whiteWins,
      draws,
      blackWins,
    },
    overviewCards: [
      { key: "games", value: games.length },
      { key: "plies", value: totalPlies },
      { key: "engines", value: engineRows.length },
      { key: "averagePlies", value: games.length ? totalPlies / games.length : null },
      { key: "skipped", value: skippedGames },
    ],
    engineRows,
  };
}
