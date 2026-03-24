import { DataFrame, GameData, Keys } from "./core.js";

const DEFAULT_COMMENT_KEYS = [Keys.SCORE, Keys.DEPTH, Keys.SELDEPTH, Keys.TIME_USED_RAW, Keys.NODES];

export function extractPgns(pgnText) {
  if (!pgnText || !pgnText.trim()) {
    return [];
  }
  const normalized = pgnText.replace(/\r/g, "");
  const lines = normalized.split("\n");
  const pgns = [];
  let current = [];
  lines.forEach((line) => {
    if (line.startsWith("[Event ") && current.length) {
      pgns.push(current.join("\n"));
      current = [];
    }
    current.push(line);
  });
  if (current.length) {
    pgns.push(current.join("\n"));
  }
  return pgns.filter((item) => item.trim());
}

function parseHeaders(pgnText) {
  return Object.fromEntries([...pgnText.matchAll(/\[(\w+) "([^"]*)"\]/g)].map((match) => [match[1], match[2]]));
}

export function parsePgn(pgnText) {
  const normalized = pgnText.replace(/\r/g, "");
  const headers = parseHeaders(normalized);
  const moveSection = normalized.split(/\n\s*\n/).slice(1).join("\n\n").trim();
  return new GameData(headers, moveSection, DEFAULT_COMMENT_KEYS);
}

export async function parsePgnCollection(pgnText, onProgress = () => {}) {
  const pgns = extractPgns(pgnText);
  const games = [];
  const frames = [];
  let skippedGames = 0;

  if (!pgns.length) {
    onProgress(100);
    return { games, dataframe: new DataFrame(), skippedGames };
  }

  for (let index = 0; index < pgns.length; index += 1) {
    try {
      const game = parsePgn(pgns[index]);
      games.push(game);
      frames.push(game.toDataFrame());
    } catch (error) {
      console.warn("Skipping PGN during insights parsing:", error);
      skippedGames += 1;
    }
    onProgress(60 + ((index + 1) / pgns.length) * 40);
    await Promise.resolve();
  }

  return {
    games,
    dataframe: DataFrame.concat(...frames),
    skippedGames,
  };
}
