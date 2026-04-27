/**
 * Admin Charts - handles Chart.js rendering with HTMX integration
 */

const HOVER_GUIDE = {
  id: "hoverGuide",
  afterDatasetsDraw(chart) {
    const active = chart.tooltip?.getActiveElements?.() ?? [];
    if (!active.length) return;
    const { ctx, chartArea } = chart;
    const x = active[0].element.x;
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(x, chartArea.top);
    ctx.lineTo(x, chartArea.bottom);
    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(0, 0, 0, 0.18)";
    ctx.stroke();
    ctx.restore();
  },
};

const NUMBER_FMT = new Intl.NumberFormat();

// Series labels come from model field values (potentially user-controlled),
// so escape before splicing into innerHTML.
const escapeHTML = (s) =>
  String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

const formatNumber = (n) => {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return NUMBER_FMT.format(Math.round(n * 100) / 100);
};

const formatDate = (iso) => {
  if (!iso) return "";
  // Parse YYYY-MM-DD as UTC so the local timezone doesn't shift the rendered day.
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  const date = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
};

const summarizeSeries = (values, mode) => {
  const visible = values.filter((v) => v !== null && v !== undefined);
  if (!visible.length) return 0;
  switch (mode) {
    case "avg":
      return visible.reduce((a, b) => a + b, 0) / visible.length;
    case "max":
      return Math.max(...visible);
    case "sum":
    default:
      return visible.reduce((a, b) => a + b, 0);
  }
};

const aggregateLabel = (mode) => {
  switch (mode) {
    case "avg":
      return "Avg";
    case "max":
      return "Max";
    case "sum":
    default:
      return "Sum";
  }
};

const bucketTotals = (visibleDatasets, length) => {
  const totals = Array.from({ length }, () => 0);
  visibleDatasets.forEach(({ ds }) => {
    for (let i = 0; i < length; i++) {
      totals[i] += Number(ds.data[i]) || 0;
    }
  });
  return totals;
};

const seriesColor = (dataset) =>
  dataset.hoverBackgroundColor || dataset.backgroundColor || "rgba(0,0,0,0.4)";

const AGG_CLS = "inline-flex items-baseline gap-1.5";
const PILL_BASE =
  "inline-flex items-baseline gap-1.5 rounded-full border border-black/10 px-2 py-0.5";
const PILL_BTN = `${PILL_BASE} hover:bg-black/5 transition-colors cursor-pointer`;

const renderChip = ({ ds, index, value, dimCls, clickable }) => {
  const tag = clickable ? "button" : "span";
  const attrs = clickable ? `type="button" data-series-toggle data-series-index="${index}"` : "";
  const cls = clickable ? PILL_BTN : PILL_BASE;
  return `
    <${tag} ${attrs} class="${cls} ${dimCls}">
      <svg class="self-center w-2 h-2 rounded-sm" viewBox="0 0 8 8">
        <rect width="8" height="8" rx="1.5" fill="${escapeHTML(seriesColor(ds))}"></rect>
      </svg>
      <span class="text-black/60">${escapeHTML(ds.label || "")}</span>
      <span class="font-semibold text-black/80 tabular-nums">${formatNumber(value)}</span>
    </${tag}>
  `;
};

const renderStats = (root, state, hoveredIndex, { force = false } = {}) => {
  // Chart.js fires onHover on every mousemove. Skip rebuilds when nothing changed.
  if (!force && state.lastHoveredIndex === hoveredIndex) return;
  state.lastHoveredIndex = hoveredIndex;

  const seriesEl = root.querySelector("[data-stats-series]");
  const aggEl = root.querySelector("[data-stats-aggregates]");
  const labelEl = root.querySelector("[data-stats-label]");
  if (!seriesEl || !aggEl || !labelEl) return;

  const { chart, meta } = state;
  const aggregates = Array.isArray(meta.aggregates) ? meta.aggregates : [];
  const primaryAggregate = aggregates[0] || null;
  const datasets = chart.data.datasets;
  const labels = chart.data.labels || [];
  const grouped = datasets.length > 1;

  // Period range is shown on the x-axis row; the label only fills with the
  // hovered date so we don't write the same range twice.
  labelEl.textContent =
    hoveredIndex !== null && labels[hoveredIndex] !== undefined
      ? formatDate(labels[hoveredIndex])
      : "";

  // Chart-level aggregate readouts: cross-series period rollups, hidden on hover
  // so the user knows the right slot is now showing the hovered day, not the period.
  if (hoveredIndex === null && aggregates.length && labels.length) {
    const visibleDatasets = datasets
      .map((ds, i) => ({ ds, i }))
      .filter(({ i }) => chart.isDatasetVisible(i));
    const totals = bucketTotals(visibleDatasets, labels.length);
    aggEl.innerHTML = aggregates
      .map((mode) => {
        const value = summarizeSeries(totals, mode);
        return `
          <span class="${AGG_CLS}">
            <span class="text-black/50">${aggregateLabel(mode)}</span>
            <span class="font-semibold text-black/80 tabular-nums">${formatNumber(value)}</span>
          </span>
        `;
      })
      .join("");
  } else {
    aggEl.innerHTML = "";
  }

  // Per-series chips also serve as the color legend, so they're always rendered.
  // Toggling the only series on a single-series chart would empty the chart, so
  // it stays static.
  seriesEl.innerHTML = datasets
    .map((ds, i) => {
      const visible = chart.isDatasetVisible(i);
      const value =
        hoveredIndex !== null
          ? Number(ds.data[hoveredIndex]) || 0
          : summarizeSeries(ds.data, primaryAggregate || "sum");
      return renderChip({
        ds,
        index: i,
        value,
        dimCls: !visible ? "opacity-40" : state.emptyFlags[i] ? "opacity-50" : "",
        clickable: grouped,
      });
    })
    .join("");
};

const renderAxis = (root, labels) => {
  const axis = root.querySelector(".chart-axis");
  if (!axis || !labels?.length) return;
  axis.classList.remove("hidden");
  const start = axis.querySelector("[data-axis-start]");
  const end = axis.querySelector("[data-axis-end]");
  if (start) start.textContent = formatDate(labels[0]);
  if (end) end.textContent = formatDate(labels[labels.length - 1]);
};

const startChart = ({ ctx, statsRoot, data }) => {
  data.options = data.options || {};

  const state = {
    chart: null,
    meta: data.plain || {},
    emptyFlags: data.data.datasets.map((ds) => summarizeSeries(ds.data, "sum") === 0),
    lastHoveredIndex: undefined,
    cleanup: () => {},
  };

  data.options.onHover = (event, elements) => {
    const idx = elements?.[0]?.index ?? null;
    if (statsRoot) renderStats(statsRoot, state, idx);
  };

  state.chart = new Chart(ctx, {
    ...data,
    plugins: [HOVER_GUIDE, ...(data.plugins || [])],
  });

  const onMouseLeave = () => {
    if (statsRoot) renderStats(statsRoot, state, null);
  };
  ctx.addEventListener("mouseleave", onMouseLeave);

  let onClick = null;
  if (statsRoot) {
    onClick = (event) => {
      const btn = event.target.closest("[data-series-toggle]");
      if (!btn) return;
      event.preventDefault();
      const idx = Number(btn.dataset.seriesIndex);
      state.chart.setDatasetVisibility(idx, !state.chart.isDatasetVisible(idx));
      state.chart.update();
      renderStats(statsRoot, state, state.lastHoveredIndex ?? null, { force: true });
    };
    statsRoot.addEventListener("click", onClick);
  }

  state.cleanup = () => {
    state.chart.destroy();
    ctx.removeEventListener("mouseleave", onMouseLeave);
    if (onClick) statsRoot.removeEventListener("click", onClick);
  };
  return state;
};

window.AdminCharts = {
  render: (slug) => {
    const ctx = document.getElementById(`card-chart-${slug}`);
    const dataElement = document.getElementById(slug);
    const emptyState = document.getElementById(`card-chart-${slug}-empty`);
    const wrapper = document.querySelector(`[data-chart-id="${slug}"]`);
    const statsRoot = document.getElementById(`card-chart-${slug}-stats`);

    if (!ctx || !dataElement) return;

    const data = JSON.parse(dataElement.textContent);
    const hasData =
      data.data?.datasets?.some((ds) => ds.data?.some((v) => v != null && v !== 0)) ?? false;

    if (ctx._chartState) {
      ctx._chartState.cleanup();
      ctx._chartState = null;
    }

    if (!hasData) {
      ctx.classList.add("hidden!");
      if (emptyState) emptyState.classList.remove("hidden");
      if (statsRoot) statsRoot.classList.add("hidden");
      return;
    }

    ctx.classList.remove("hidden!");
    if (emptyState) emptyState.classList.add("hidden");
    if (statsRoot) statsRoot.classList.remove("hidden");

    if (typeof Chart === "undefined") return;

    const state = startChart({ ctx, statsRoot, data });
    ctx._chartState = state;

    if (statsRoot) renderStats(statsRoot, state, null, { force: true });
    if (wrapper) renderAxis(wrapper, state.chart.data.labels);
  },

  renderAll: function (container) {
    const charts = container.querySelectorAll ? container.querySelectorAll("[data-chart-id]") : [];
    charts.forEach((el) => {
      const slug = el.getAttribute("data-chart-id");
      if (slug) this.render(slug);
    });

    if (container.getAttribute?.("data-chart-id")) {
      this.render(container.getAttribute("data-chart-id"));
    }
  },
};

window.AdminCharts.renderAll(document);

document.addEventListener("htmx:afterSettle", (evt) => {
  window.AdminCharts.renderAll(evt.target);
});
