export const Keys = Object.freeze({
  DEPTH: "DEPTH",
  SELDEPTH: "SELDEPTH",
  NODES: "NODES",
  TIME_USED_RAW: "TIME_USED_RAW",
  NPS_RAW: "NPS_RAW",
  TIME_LEFT_RAW: "TIME_LEFT_RAW",
  NPS: "NPS",
  TIME_USED: "TIME_USED",
  TIME_LEFT: "TIME_LEFT",
  PLY: "PLY",
  MOVE_NUMBER: "MOVE_NUMBER",
  REL_TIME_USED: "REL_TIME_USED",
  REL_TIME_USED_TOTAL: "REL_TIME_USED_TOTAL",
  STM: "STM",
  BOOK: "BOOK",
  TC: "TC",
  FEN: "FEN",
  SCALE_FACTOR: "SCALE_FACTOR",
  END_TIME: "END_TIME",
  RESULT: "RESULT",
  SCORE: "SCORE",
  NAME: "NAME",
});

export function formatMetricValue(key, value) {
  if (value == null || !Number.isFinite(value)) {
    return "-";
  }
  if (key === Keys.NODES || key === Keys.NPS || key === Keys.NPS_RAW) {
    if (value >= 1e6) {
      return `${(value / 1e6).toFixed(2)}M`;
    }
    if (value >= 1e3) {
      return `${(value / 1e3).toFixed(2)}k`;
    }
    return value.toFixed(0);
  }
  if (key === Keys.TIME_USED || key === Keys.TIME_LEFT || key === Keys.TIME_USED_RAW || key === Keys.TIME_LEFT_RAW) {
    if (value >= 1000) {
      return `${(value / 1000).toFixed(2)} s`;
    }
    return `${value.toFixed(1)} ms`;
  }
  return value.toFixed(2);
}

export class MoveData {
  constructor(keys) {
    this.data = {};
    keys.forEach((key) => {
      this.data[key] = null;
    });
  }
}

export class DataFrame {
  constructor(data = {}) {
    this.data = {};
    const keys = Object.keys(data);
    if (!keys.length) {
      return;
    }
    const length = data[keys[0]].length;
    if (!keys.every((key) => data[key].length === length)) {
      throw new Error("All DataFrame columns must have the same length.");
    }
    this.data = data;
  }

  static concat(...frames) {
    const validFrames = frames.filter((frame) => frame instanceof DataFrame && Object.keys(frame.data).length > 0);
    if (!validFrames.length) {
      return new DataFrame();
    }
    const commonKeys = validFrames.reduce(
      (keys, frame) => keys.filter((key) => Object.prototype.hasOwnProperty.call(frame.data, key)),
      Object.keys(validFrames[0].data),
    );
    const merged = {};
    commonKeys.forEach((key) => {
      merged[key] = validFrames.flatMap((frame) => frame.data[key]);
    });
    return new DataFrame(merged);
  }

  hasColumn(name) {
    return Object.prototype.hasOwnProperty.call(this.data, name);
  }

  getColumn(name) {
    return this.hasColumn(name) ? this.data[name] : [];
  }

  rowCount() {
    const keys = Object.keys(this.data);
    return keys.length ? this.data[keys[0]].length : 0;
  }
}

export class GameData {
  constructor(headers, moveCommentsText, textKeys) {
    this.rawHeaders = headers;
    this.textKeys = textKeys;
    this.dataKeys = new Set(textKeys);
    this.headers = this.#deriveHeaderData(headers);
    this.moves = this.#parseMoves(moveCommentsText);
    this.#deriveGameData();
  }

  #headerHas(key) {
    return Object.prototype.hasOwnProperty.call(this.headers, key);
  }

  #dataHas(key) {
    return this.dataKeys.has(key);
  }

  #parseMoves(moveCommentsText) {
    const comments = moveCommentsText.match(/\{([^}]*)\}/g) || [];
    return comments.map((comment) => this.#parseMove(comment.replace(/[{}]/g, "").trim()));
  }

  #parseEvalToken(token) {
    return Number.parseFloat(String(token).trim().replaceAll("+", "").replace(/m/gi, ""));
  }

  #parseTimeToken(rawValue, unit) {
    const value = Number.parseFloat(String(rawValue).trim());
    if (!Number.isFinite(value)) {
      return null;
    }
    if (String(unit).toLowerCase() === "s") {
      return value * 1000;
    }
    return value;
  }

  #parseOldMoveComment(comment) {
    const match = comment.match(
      /^([+\-]?(?:M)?\d+(?:\.\d+)?)\s+(\d+)(?:\/(\d+))?\s+([0-9]+(?:\.\d+)?)\s+(\d+)(?:\s+.*)?$/i,
    );
    if (!match) {
      return null;
    }
    return {
      score: this.#parseEvalToken(match[1]),
      depth: Number.parseFloat(match[2]),
      seldepth: Number.parseFloat(match[3] || match[2]),
      timeUsedRaw: Number.parseFloat(match[4]),
      nodes: Number.parseFloat(match[5]),
    };
  }

  #parseNewMoveComment(comment) {
    const scoreDepth = comment.match(/^([+\-]?(?:M)?\d+(?:\.\d+)?)\/(\d+)/i);
    const time = comment.match(/(?:^|\s)([0-9]+(?:\.\d+)?)(ms|s)\b/i);
    const nodes = comment.match(/\bn=(\d+)\b/i);
    const seldepth = comment.match(/\bsd=(\d+)\b/i);
    if (!scoreDepth || !time || !nodes || !seldepth) {
      return null;
    }
    return {
      score: this.#parseEvalToken(scoreDepth[1]),
      depth: Number.parseFloat(scoreDepth[2]),
      seldepth: Number.parseFloat(seldepth[1]),
      timeUsedRaw: this.#parseTimeToken(time[1], time[2]),
      nodes: Number.parseFloat(nodes[1]),
    };
  }

  #parseMove(comment) {
    const move = new MoveData(this.textKeys);
    if (/book/i.test(comment)) {
      move.data[Keys.BOOK] = true;
      this.dataKeys.add(Keys.BOOK);
    }

    const parsed = this.#parseNewMoveComment(comment) || this.#parseOldMoveComment(comment);
    if (!parsed) {
      if (/book/i.test(comment)) {
        return move;
      }
      throw new Error(`Unsupported move comment format: ${comment}`);
    }

    const valuesByKey = {
      [Keys.SCORE]: parsed.score,
      [Keys.DEPTH]: parsed.depth,
      [Keys.SELDEPTH]: parsed.seldepth,
      [Keys.TIME_USED_RAW]: parsed.timeUsedRaw,
      [Keys.NODES]: parsed.nodes,
    };
    this.textKeys.forEach((key) => {
      if (Object.prototype.hasOwnProperty.call(valuesByKey, key)) {
        move.data[key] = valuesByKey[key];
      }
    });
    return move;
  }

  #deriveHeaderData(headers) {
    const fields = {};
    if (headers.TimeControl) {
      const parsed = this.#parseTimeControlHeader(headers.TimeControl);
      if (parsed) {
        fields[Keys.TC] = parsed;
      }
    }
    if (headers.GameEndTime) {
      fields[Keys.END_TIME] = new Date(headers.GameEndTime).getTime();
    }
    if (headers.ScaleFactor) {
      fields[Keys.SCALE_FACTOR] = Number.parseFloat(headers.ScaleFactor);
    }
    if (headers.Result) {
      fields[Keys.RESULT] = headers.Result === "1-0" ? 1 : headers.Result === "0-1" ? 0 : 0.5;
    }
    if (headers.FEN) {
      fields[Keys.FEN] = headers.FEN;
      fields[Keys.STM] = headers.FEN.includes(" w ") ? "w" : "b";
      fields[Keys.MOVE_NUMBER] = Number.parseInt(headers.FEN.split(" ")[5], 10) || 1;
    } else {
      fields[Keys.FEN] = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
      fields[Keys.STM] = "w";
      fields[Keys.MOVE_NUMBER] = 1;
    }
    if (headers.White && headers.Black) {
      fields[Keys.NAME] = { w: headers.White, b: headers.Black };
    }
    return fields;
  }

  #parseTimeControlHeader(rawValue) {
    if (!rawValue) {
      return null;
    }
    let timeControl = String(rawValue).trim();
    if (timeControl.includes("/")) {
      const slashIndex = timeControl.indexOf("/");
      const prefix = timeControl.slice(0, slashIndex).trim();
      if (/^\d+$/.test(prefix)) {
        timeControl = timeControl.slice(slashIndex + 1).trim();
      }
    }
    const plusIndex = timeControl.indexOf("+");
    const baseText = plusIndex >= 0 ? timeControl.slice(0, plusIndex) : timeControl;
    const incrementText = plusIndex >= 0 ? timeControl.slice(plusIndex + 1) : "0";
    const baseSeconds = Number.parseFloat(baseText);
    const incrementSeconds = Number.parseFloat(incrementText || "0");
    if (!Number.isFinite(baseSeconds)) {
      return null;
    }
    return [
      baseSeconds * 1000,
      Number.isFinite(incrementSeconds) ? incrementSeconds * 1000 : 0,
    ];
  }

  #updateMoveKeys() {
    if (!this.moves.length) {
      this.dataKeys = new Set(this.textKeys);
      return;
    }
    this.dataKeys = new Set(Object.keys(this.moves[0].data));
  }

  #deriveStm() {
    if (!this.#headerHas(Keys.STM)) {
      return;
    }
    let stm = this.headers[Keys.STM];
    this.moves.forEach((move) => {
      move.data[Keys.STM] = stm;
      stm = stm === "w" ? "b" : "w";
    });
    this.#updateMoveKeys();
  }

  #deriveMoveNumber() {
    if (!this.#headerHas(Keys.MOVE_NUMBER) || !this.#dataHas(Keys.STM)) {
      return;
    }
    let moveNumber = this.headers[Keys.MOVE_NUMBER];
    this.moves.forEach((move) => {
      move.data[Keys.MOVE_NUMBER] = moveNumber;
      if (move.data[Keys.STM] === "b") {
        moveNumber += 1;
      }
    });
    this.#updateMoveKeys();
  }

  #derivePly() {
    this.moves.forEach((move, index) => {
      move.data[Keys.PLY] = index + 1;
    });
    this.#updateMoveKeys();
  }

  #deriveTimeLeft() {
    if (this.#dataHas(Keys.TIME_LEFT_RAW) || !this.#headerHas(Keys.TC) || !this.#dataHas(Keys.TIME_USED_RAW)) {
      return;
    }
    let whiteTime = this.headers[Keys.TC][0] + this.headers[Keys.TC][1];
    let blackTime = this.headers[Keys.TC][0] + this.headers[Keys.TC][1];
    this.moves.forEach((move) => {
      if (move.data[Keys.STM] === "w") {
        move.data[Keys.TIME_LEFT_RAW] = whiteTime;
        whiteTime -= move.data[Keys.TIME_USED_RAW] - this.headers[Keys.TC][1];
      } else {
        move.data[Keys.TIME_LEFT_RAW] = blackTime;
        blackTime -= move.data[Keys.TIME_USED_RAW] - this.headers[Keys.TC][1];
      }
    });
    this.#updateMoveKeys();
  }

  #deriveNpsRaw() {
    if (this.#dataHas(Keys.NPS_RAW) || !this.#dataHas(Keys.NODES) || !this.#dataHas(Keys.TIME_USED_RAW)) {
      return;
    }
    this.moves.forEach((move) => {
      move.data[Keys.NPS_RAW] = (move.data[Keys.NODES] * 1000) / Math.max(1, move.data[Keys.TIME_USED_RAW]);
    });
    this.#updateMoveKeys();
  }

  #deriveRelativeTimes() {
    const rawScaleFactor = this.headers[Keys.SCALE_FACTOR];
    const scaleFactor = Number.isFinite(rawScaleFactor) && rawScaleFactor > 0 ? rawScaleFactor : 1;
    if (this.#dataHas(Keys.TIME_USED_RAW) && !this.#dataHas(Keys.TIME_USED)) {
      this.moves.forEach((move) => {
        move.data[Keys.TIME_USED] = this.#headerHas(Keys.SCALE_FACTOR)
          ? move.data[Keys.TIME_USED_RAW] * scaleFactor
          : move.data[Keys.TIME_USED_RAW];
      });
    }
    if (this.#dataHas(Keys.TIME_LEFT_RAW) && !this.#dataHas(Keys.TIME_LEFT)) {
      this.moves.forEach((move) => {
        move.data[Keys.TIME_LEFT] = this.#headerHas(Keys.SCALE_FACTOR)
          ? move.data[Keys.TIME_LEFT_RAW] * scaleFactor
          : move.data[Keys.TIME_LEFT_RAW];
      });
    }
    if (this.#dataHas(Keys.NPS_RAW) && !this.#dataHas(Keys.NPS)) {
      this.moves.forEach((move) => {
        move.data[Keys.NPS] = this.#headerHas(Keys.SCALE_FACTOR)
          ? move.data[Keys.NPS_RAW] / scaleFactor
          : move.data[Keys.NPS_RAW];
      });
    }
    this.#updateMoveKeys();

    if (this.#dataHas(Keys.TIME_LEFT) && this.#dataHas(Keys.TIME_USED) && !this.#dataHas(Keys.REL_TIME_USED)) {
      this.moves.forEach((move) => {
        move.data[Keys.REL_TIME_USED] = move.data[Keys.TIME_USED] / move.data[Keys.TIME_LEFT];
      });
    }
    if (this.#headerHas(Keys.TC) && this.#dataHas(Keys.TIME_USED) && !this.#dataHas(Keys.REL_TIME_USED_TOTAL)) {
      const totalBase = this.#headerHas(Keys.SCALE_FACTOR)
        ? this.headers[Keys.TC][0] * scaleFactor
        : this.headers[Keys.TC][0];
      this.moves.forEach((move) => {
        move.data[Keys.REL_TIME_USED_TOTAL] = move.data[Keys.TIME_USED] / totalBase;
      });
    }
    this.#updateMoveKeys();
  }

  #deriveNames() {
    if (!this.#headerHas(Keys.NAME)) {
      return;
    }
    this.moves.forEach((move) => {
      move.data[Keys.NAME] = this.headers[Keys.NAME][move.data[Keys.STM]];
    });
    this.#updateMoveKeys();
  }

  #deriveResults() {
    if (!this.#headerHas(Keys.RESULT)) {
      return;
    }
    const result = this.headers[Keys.RESULT];
    this.moves.forEach((move) => {
      move.data[Keys.RESULT] =
        (result === 1 && move.data[Keys.STM] === "w") || (result === 0 && move.data[Keys.STM] === "b")
          ? 1
          : (result === 0 && move.data[Keys.STM] === "w") || (result === 1 && move.data[Keys.STM] === "b")
            ? 0
            : 0.5;
    });
    this.#updateMoveKeys();
  }

  #deriveGameData() {
    this.#deriveStm();
    this.#deriveMoveNumber();
    this.#derivePly();
    this.#deriveTimeLeft();
    this.#deriveNpsRaw();
    this.#deriveNames();
    this.#deriveResults();
    this.#deriveRelativeTimes();
  }

  toDataFrame() {
    const headers = Array.from(this.dataKeys);
    const data = {};
    headers.forEach((header) => {
      data[header] = [];
    });
    this.moves.forEach((move) => {
      headers.forEach((header) => {
        data[header].push(move.data[header] ?? null);
      });
    });
    return new DataFrame(data);
  }
}
