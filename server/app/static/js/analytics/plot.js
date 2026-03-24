import { Keys, formatMetricValue } from "./core.js";
import { binData } from "./binning.js";

const PALETTE = ["#d64550", "#2a7de1", "#2d9d78", "#ef8f00", "#8f63d2", "#0f9fb7", "#d06aa7", "#65758b"];

function keyLabel(key) {
  switch (key) {
    case Keys.PLY:
      return "Ply";
    case Keys.MOVE_NUMBER:
      return "Move";
    case Keys.TIME_USED:
      return "Time";
    case Keys.TIME_LEFT:
      return "Time Left";
    default:
      return key.replaceAll("_", " ");
  }
}

function numericColumns(dataframe) {
  return Object.keys(dataframe.data).filter((key) => dataframe.getColumn(key).some((value) => Number.isFinite(value)));
}

function axisOptions(dataframe) {
  const preferredOrder = [
    Keys.PLY,
    Keys.MOVE_NUMBER,
    Keys.TIME_USED,
    Keys.TIME_LEFT,
    Keys.NPS,
    Keys.NODES,
    Keys.SCORE,
    Keys.DEPTH,
    Keys.SELDEPTH,
    Keys.REL_TIME_USED,
    Keys.REL_TIME_USED_TOTAL,
    Keys.RESULT,
  ];
  const present = new Set(numericColumns(dataframe));
  const ordered = preferredOrder.filter((key) => present.has(key));
  const extras = Array.from(present).filter((key) => !preferredOrder.includes(key)).sort();
  return [...ordered, ...extras].map((key) => ({ value: key, label: keyLabel(key) }));
}

function color(index) {
  return PALETTE[index % PALETTE.length];
}

function collectSeries(dataframe, xKey, yKey) {
  const names = dataframe.getColumn(Keys.NAME);
  const xValues = dataframe.getColumn(xKey);
  const yValues = dataframe.getColumn(yKey);
  const grouped = new Map();

  for (let index = 0; index < names.length; index += 1) {
    const name = names[index];
    const x = xValues[index];
    const y = yValues[index];
    if (!name || !Number.isFinite(x) || !Number.isFinite(y)) {
      continue;
    }
    if (!grouped.has(name)) {
      grouped.set(name, []);
    }
    grouped.get(name).push({ x, y });
  }

  return Array.from(grouped.entries())
    .map(([name, rows]) => {
      rows.sort((left, right) => left.x - right.x);
      const bucketCount = Math.max(1, Math.min(140, Math.floor(rows.length / 8)));
      return {
        name,
        points: binData(
          rows.map((row) => row.x),
          rows.map((row) => row.y),
          bucketCount,
        ),
      };
    })
    .filter((series) => series.points.length > 0);
}

function createSvgElement(tag, attrs = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  Object.entries(attrs).forEach(([name, value]) => {
    element.setAttribute(name, String(value));
  });
  return element;
}

function pathFromPoints(points, scaleX, scaleY) {
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${scaleX(point.x).toFixed(2)} ${scaleY(point.y).toFixed(2)}`)
    .join(" ");
}

function polygonFromBand(points, scaleX, scaleY) {
  const upper = points.map((point) => `${scaleX(point.x).toFixed(2)},${scaleY(point.y + point.std).toFixed(2)}`);
  const lower = points
    .slice()
    .reverse()
    .map((point) => `${scaleX(point.x).toFixed(2)},${scaleY(point.y - point.std).toFixed(2)}`);
  return [...upper, ...lower].join(" ");
}

function makeScale(domainMin, domainMax, rangeMin, rangeMax) {
  if (domainMin === domainMax) {
    return () => (rangeMin + rangeMax) / 2;
  }
  const factor = (rangeMax - rangeMin) / (domainMax - domainMin);
  return (value) => rangeMin + (value - domainMin) * factor;
}

function paddedDomain(minimum, maximum) {
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum)) {
    return [0, 1];
  }
  if (minimum === maximum) {
    const delta = minimum === 0 ? 1 : Math.abs(minimum) * 0.1;
    return [minimum - delta, maximum + delta];
  }
  const padding = (maximum - minimum) * 0.06;
  return [minimum - padding, maximum + padding];
}

function resolveDomain(rawMin, rawMax, overrideMin, overrideMax) {
  let [minimum, maximum] = paddedDomain(rawMin, rawMax);
  if (Number.isFinite(overrideMin)) {
    minimum = overrideMin;
  }
  if (Number.isFinite(overrideMax)) {
    maximum = overrideMax;
  }
  if (!Number.isFinite(minimum) || !Number.isFinite(maximum) || minimum === maximum || minimum > maximum) {
    return paddedDomain(rawMin, rawMax);
  }
  return [minimum, maximum];
}

function appendText(svg, text, attrs) {
  const element = createSvgElement("text", attrs);
  element.textContent = text;
  svg.appendChild(element);
}

function renderLegend(container, series) {
  const legend = document.createElement("div");
  legend.className = "analytics-legend";
  series.forEach((entry, index) => {
    const item = document.createElement("div");
    item.className = "analytics-legend-item";
    const swatch = document.createElement("span");
    swatch.className = "analytics-legend-swatch";
    swatch.style.backgroundColor = color(index);
    const label = document.createElement("span");
    label.textContent = entry.name;
    item.append(swatch, label);
    legend.appendChild(item);
  });
  container.appendChild(legend);
}

export function renderPlot(container, dataframe, options, emptyLabel) {
  container.replaceChildren();
  const series = collectSeries(dataframe, options.xKey, options.yKey);
  if (!series.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.textContent = emptyLabel;
    container.appendChild(empty);
    return;
  }

  const width = 980;
  const height = 420;
  const margin = { top: 24, right: 20, bottom: 56, left: 72 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;

  const xValues = series.flatMap((entry) => entry.points.map((point) => point.x));
  const yMinRaw = Math.min(...series.flatMap((entry) => entry.points.map((point) => (options.showDeviation ? point.y - point.std : point.y))));
  const yMaxRaw = Math.max(...series.flatMap((entry) => entry.points.map((point) => (options.showDeviation ? point.y + point.std : point.y))));
  const [minX, maxX] = resolveDomain(Math.min(...xValues), Math.max(...xValues), options.xMin, options.xMax);
  const [minY, maxY] = resolveDomain(yMinRaw, yMaxRaw, options.yMin, options.yMax);
  const scaleX = makeScale(minX, maxX, margin.left, margin.left + plotWidth);
  const scaleY = makeScale(minY, maxY, margin.top + plotHeight, margin.top);

  const svg = createSvgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    class: "analytics-plot-svg",
    role: "img",
    "aria-label": `${keyLabel(options.yKey)} over ${keyLabel(options.xKey)}`,
  });

  for (let tick = 0; tick <= 4; tick += 1) {
    const x = margin.left + (plotWidth / 4) * tick;
    const y = margin.top + (plotHeight / 4) * tick;
    svg.appendChild(createSvgElement("line", { x1: x, x2: x, y1: margin.top, y2: margin.top + plotHeight, class: "analytics-grid-line" }));
    svg.appendChild(createSvgElement("line", { x1: margin.left, x2: margin.left + plotWidth, y1: y, y2: y, class: "analytics-grid-line" }));
    const xValue = minX + ((maxX - minX) / 4) * tick;
    const yValue = maxY - ((maxY - minY) / 4) * tick;
    appendText(svg, formatMetricValue(options.xKey, xValue), { x, y: height - 18, class: "analytics-axis-text", "text-anchor": "middle" });
    appendText(svg, formatMetricValue(options.yKey, yValue), { x: margin.left - 10, y: y + 4, class: "analytics-axis-text", "text-anchor": "end" });
  }

  svg.appendChild(createSvgElement("line", { x1: margin.left, x2: margin.left, y1: margin.top, y2: margin.top + plotHeight, class: "analytics-axis-line" }));
  svg.appendChild(
    createSvgElement("line", {
      x1: margin.left,
      x2: margin.left + plotWidth,
      y1: margin.top + plotHeight,
      y2: margin.top + plotHeight,
      class: "analytics-axis-line",
    }),
  );

  appendText(svg, keyLabel(options.xKey), { x: margin.left + plotWidth / 2, y: height - 4, class: "analytics-axis-label", "text-anchor": "middle" });
  const yLabel = createSvgElement("text", {
    x: 18,
    y: margin.top + plotHeight / 2,
    class: "analytics-axis-label",
    transform: `rotate(-90 18 ${margin.top + plotHeight / 2})`,
    "text-anchor": "middle",
  });
  yLabel.textContent = keyLabel(options.yKey);
  svg.appendChild(yLabel);

  series.forEach((entry, index) => {
    if (options.showDeviation) {
      svg.appendChild(
        createSvgElement("polygon", {
          points: polygonFromBand(entry.points, scaleX, scaleY),
          fill: color(index),
          class: "analytics-band",
        }),
      );
    }
    svg.appendChild(
      createSvgElement("path", {
        d: pathFromPoints(entry.points, scaleX, scaleY),
        fill: "none",
        stroke: color(index),
        "stroke-width": 2.5,
        "stroke-linejoin": "round",
        "stroke-linecap": "round",
      }),
    );
  });

  container.appendChild(svg);
  renderLegend(container, series);
}

export function buildAxisOptions(dataframe) {
  return axisOptions(dataframe);
}
