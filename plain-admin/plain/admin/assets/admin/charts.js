/**
 * Admin Charts - handles Chart.js rendering with HTMX integration
 */
window.AdminCharts = {
  /**
   * Render a chart by slug
   * @param {string} slug - The chart's unique identifier
   */
  render: (slug) => {
    const ctx = document.getElementById(`card-chart-${slug}`);
    const dataElement = document.getElementById(slug);
    const emptyState = document.getElementById(`card-chart-${slug}-empty`);

    if (!ctx || !dataElement) return;

    const dataText = dataElement.textContent;
    const data = JSON.parse(dataText);
    const hasData = data.data?.datasets?.some((ds) => ds.data?.some((v) => v > 0)) ?? false;

    // Destroy existing chart if present
    if (ctx._chart) {
      ctx._chart.destroy();
      ctx._chart = null;
    }

    // Handle empty state
    if (!hasData) {
      ctx.style.display = "none";
      if (emptyState) emptyState.classList.remove("hidden");
      return;
    }

    ctx.style.display = "";
    if (emptyState) emptyState.classList.add("hidden");

    // Only create chart if Chart.js is loaded
    if (typeof Chart === "undefined") return;

    ctx._chart = new Chart(ctx, data);
  },

  /**
   * Render all charts in a container
   * @param {Element} container - DOM element to search for charts
   */
  renderAll: function (container) {
    const charts = container.querySelectorAll ? container.querySelectorAll("[data-chart-id]") : [];
    charts.forEach((el) => {
      const slug = el.getAttribute("data-chart-id");
      if (slug) this.render(slug);
    });

    // Check if container itself is a chart
    if (container.getAttribute?.("data-chart-id")) {
      this.render(container.getAttribute("data-chart-id"));
    }
  },
};

// Render any charts already on the page (deferred script runs after HTML is parsed)
window.AdminCharts.renderAll(document);

// HTMX integration - render charts after content swaps
document.addEventListener("htmx:afterSettle", (evt) => {
  window.AdminCharts.renderAll(evt.target);
});
