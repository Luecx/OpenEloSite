import { Keys, formatMetricValue } from "./core.js";
import { parsePgnCollection } from "./parser.js";
import { buildAxisOptions, renderPlot } from "./plot.js";
import { buildInsights } from "./summaries.js";

function setProgress(root, value) {
  const progressBar = root.querySelector("[data-analytics-progress]");
  if (progressBar) {
    progressBar.style.width = `${Math.max(0, Math.min(100, value)).toFixed(1)}%`;
  }
}

function setStatus(root, message) {
  const status = root.querySelector("[data-analytics-status]");
  if (status) {
    status.textContent = message;
  }
}

function setError(root, message) {
  const errorElement = root.querySelector("[data-analytics-error]");
  if (!errorElement) {
    return;
  }
  errorElement.hidden = false;
  errorElement.textContent = message;
}

function getTexts(root) {
  return {
    loading: root.dataset.loadingLabel || "Loading PGNs...",
    processing: root.dataset.processingLabel || "Processing PGNs...",
    complete: root.dataset.completeLabel || "Analysis complete.",
    empty: root.dataset.emptyLabel || "No PGN data available.",
    labelGames: root.dataset.labelGames || "Games",
    labelPlies: root.dataset.labelPlies || "Plies",
    labelEngines: root.dataset.labelEngines || "Engines",
    labelAveragePlies: root.dataset.labelAveragePlies || "Plies / game",
    labelSkipped: root.dataset.labelSkipped || "Skipped",
    plotEmpty: root.dataset.plotEmptyLabel || "No suitable plot data available.",
  };
}

function parseOptionalNumber(input) {
  if (!input) {
    return undefined;
  }
  const value = String(input.value || "").trim();
  if (!value) {
    return undefined;
  }
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

async function fetchTextWithProgress(url, onProgress) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    throw new Error(`Failed to load PGN (${response.status})`);
  }

  if (!response.body) {
    const text = await response.text();
    onProgress(60);
    return text;
  }

  const total = Number(response.headers.get("content-length") || "0");
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  const chunks = [];
  let received = 0;
  let fallbackProgress = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    chunks.push(value);
    received += value.byteLength;
    if (total > 0) {
      onProgress((received / total) * 60);
    } else {
      fallbackProgress = Math.min(58, fallbackProgress + 4);
      onProgress(fallbackProgress);
    }
  }

  const text = chunks.map((chunk) => decoder.decode(chunk, { stream: true })).join("") + decoder.decode();
  onProgress(60);
  return text;
}

function formatOverviewValue(card) {
  if (card.value == null) {
    return "-";
  }
  if (card.key === "averagePlies") {
    return card.value.toFixed(1);
  }
  return `${card.value}`;
}

function renderOverview(root, insights, texts) {
  const overview = root.querySelector("[data-analytics-overview]");
  if (!overview) {
    return;
  }
  const labels = {
    games: texts.labelGames,
    plies: texts.labelPlies,
    engines: texts.labelEngines,
    averagePlies: texts.labelAveragePlies,
    skipped: texts.labelSkipped,
  };
  overview.replaceChildren(
    ...insights.overviewCards.map((card) => {
      const element = document.createElement("article");
      element.className = "analytics-card";
      const label = document.createElement("span");
      label.className = "analytics-card-label";
      label.textContent = labels[card.key] || card.key;
      const value = document.createElement("div");
      value.className = "analytics-card-value";
      value.textContent = formatOverviewValue(card);
      element.append(label, value);
      return element;
    }),
  );
}

function renderResultsTable(root, insights) {
  const body = root.querySelector("[data-analytics-results-table]");
  if (!body) {
    return;
  }
  const row = document.createElement("tr");
  [insights.resultBreakdown.whiteWins, insights.resultBreakdown.draws, insights.resultBreakdown.blackWins, insights.averagePliesPerGame].forEach(
    (value, index) => {
      const cell = document.createElement("td");
      cell.textContent = index === 3 ? (value == null ? "-" : value.toFixed(1)) : `${value}`;
      row.appendChild(cell);
    },
  );
  body.replaceChildren(row);
}

function renderEngineTable(root, insights, texts) {
  const body = root.querySelector("[data-analytics-engines-table]");
  if (!body) {
    return;
  }

  const rows = insights.engineRows.map((engine) => {
    const row = document.createElement("tr");
    const values = [
      engine.name,
      `${engine.games} (${engine.whiteGames}/${engine.blackGames})`,
      `${engine.wins}-${engine.draws}-${engine.losses}`,
      engine.scorePercent == null ? "-" : `${engine.points.toFixed(1)} / ${engine.games} (${engine.scorePercent.toFixed(1)}%)`,
      `${engine.plies}`,
      formatMetricValue(Keys.DEPTH, engine.avgDepth),
      formatMetricValue(Keys.SELDEPTH, engine.avgSelDepth),
      formatMetricValue(Keys.TIME_USED, engine.avgTimeUsed),
      formatMetricValue(Keys.NODES, engine.avgNodes),
      formatMetricValue(Keys.NPS, engine.avgNps),
      engine.bookShare == null ? "-" : `${(engine.bookShare * 100).toFixed(1)}%`,
    ];
    values.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    return row;
  });

  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 11;
    cell.textContent = texts.empty;
    row.appendChild(cell);
    body.replaceChildren(row);
    return;
  }

  body.replaceChildren(...rows);
}

function renderSummary(root, insights, texts) {
  const summary = root.querySelector("[data-analytics-summary]");
  if (!summary) {
    return;
  }
  summary.textContent = `${insights.totalGames} ${texts.labelGames}, ${insights.totalPlies} ${texts.labelPlies}, ${insights.engineCount} ${texts.labelEngines}.`;
}

function populateSelect(select, options, preferredValue) {
  if (!select) {
    return;
  }
  select.replaceChildren(
    ...options.map((option) => {
      const element = document.createElement("option");
      element.value = option.value;
      element.textContent = option.label;
      if (option.value === preferredValue) {
        element.selected = true;
      }
      return element;
    }),
  );
}

function defaultX(options) {
  return options.find((option) => option.value === Keys.PLY)?.value
    || options.find((option) => option.value === Keys.MOVE_NUMBER)?.value
    || options[0]?.value
    || "";
}

function defaultY(options) {
  return options.find((option) => option.value === Keys.TIME_USED)?.value
    || options.find((option) => option.value === Keys.NPS)?.value
    || options.find((option) => option.value === Keys.SCORE)?.value
    || options[0]?.value
    || "";
}

function initPlotControls(root, bundle, texts) {
  const plotContainer = root.querySelector("[data-analytics-plot]");
  const xAxisSelect = root.querySelector("[data-plot-x-axis]");
  const yAxisSelect = root.querySelector("[data-plot-y-axis]");
  const deviationToggle = root.querySelector("[data-plot-deviation]");
  const settingsToggle = root.querySelector("[data-plot-settings-toggle]");
  const settingsPanel = root.querySelector("[data-plot-settings-panel]");
  const resetButton = root.querySelector("[data-plot-bounds-reset]");
  const xMinInput = root.querySelector("[data-plot-x-min]");
  const xMaxInput = root.querySelector("[data-plot-x-max]");
  const yMinInput = root.querySelector("[data-plot-y-min]");
  const yMaxInput = root.querySelector("[data-plot-y-max]");
  if (!plotContainer || !xAxisSelect || !yAxisSelect || !deviationToggle) {
    return;
  }

  const options = buildAxisOptions(bundle.dataframe);
  if (!options.length) {
    plotContainer.textContent = texts.plotEmpty;
    return;
  }

  populateSelect(xAxisSelect, options, defaultX(options));
  populateSelect(yAxisSelect, options, defaultY(options));

  const rerender = () => {
    renderPlot(
      plotContainer,
      bundle.dataframe,
      {
        xKey: xAxisSelect.value,
        yKey: yAxisSelect.value,
        showDeviation: deviationToggle.checked,
        xMin: parseOptionalNumber(xMinInput),
        xMax: parseOptionalNumber(xMaxInput),
        yMin: parseOptionalNumber(yMinInput),
        yMax: parseOptionalNumber(yMaxInput),
      },
      texts.plotEmpty,
    );
  };

  xAxisSelect.addEventListener("change", rerender);
  yAxisSelect.addEventListener("change", rerender);
  deviationToggle.addEventListener("change", rerender);
  [xMinInput, xMaxInput, yMinInput, yMaxInput].forEach((input) => {
    if (!input) {
      return;
    }
    input.addEventListener("change", rerender);
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        rerender();
      }
    });
  });
  if (resetButton) {
    resetButton.addEventListener("click", () => {
      [xMinInput, xMaxInput, yMinInput, yMaxInput].forEach((input) => {
        if (input) {
          input.value = "";
        }
      });
      rerender();
    });
  }
  if (settingsToggle && settingsPanel) {
    settingsToggle.addEventListener("click", (event) => {
      event.stopPropagation();
      const isHidden = settingsPanel.hidden;
      settingsPanel.hidden = !isHidden;
      settingsToggle.setAttribute("aria-expanded", isHidden ? "true" : "false");
    });
    document.addEventListener("click", (event) => {
      if (!settingsPanel.hidden && !settingsPanel.contains(event.target) && !settingsToggle.contains(event.target)) {
        settingsPanel.hidden = true;
        settingsToggle.setAttribute("aria-expanded", "false");
      }
    });
  }
  rerender();
}

async function initInsights(root) {
  const texts = getTexts(root);
  const results = root.querySelector("[data-analytics-results]");

  setStatus(root, texts.loading);
  setProgress(root, 0);

  try {
    const pgnText = await fetchTextWithProgress(root.dataset.pgnUrl, (progress) => setProgress(root, progress));
    if (!pgnText.trim()) {
      setProgress(root, 100);
      setStatus(root, texts.empty);
      setError(root, texts.empty);
      return;
    }

    setStatus(root, texts.processing);
    const bundle = await parsePgnCollection(pgnText, (progress) => setProgress(root, progress));
    const insights = buildInsights(bundle);

    if (!insights.totalGames) {
      setProgress(root, 100);
      setStatus(root, texts.empty);
      setError(root, texts.empty);
      return;
    }

    renderSummary(root, insights, texts);
    renderOverview(root, insights, texts);
    renderResultsTable(root, insights);
    renderEngineTable(root, insights, texts);
    initPlotControls(root, bundle, texts);
    results.hidden = false;
    setProgress(root, 100);
    setStatus(root, texts.complete);
  } catch (error) {
    console.error(error);
    setProgress(root, 100);
    setStatus(root, error.message || "Analysis failed.");
    setError(root, error.message || "Analysis failed.");
  }
}

document.querySelectorAll("[data-pgn-insights]").forEach((root) => {
  initInsights(root);
});
