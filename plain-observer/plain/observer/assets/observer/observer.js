// Observer JS - CSP-compliant timeline positioning and utilities

// Apply CSS custom properties for timeline positioning
function applyTimelinePositioning() {
  document
    .querySelectorAll("[data-start-percent][data-width-percent]")
    .forEach((el) => {
      const start = el.dataset.startPercent;
      const width = el.dataset.widthPercent;
      el.style.setProperty("--start", `${start}%`);
      el.style.setProperty("--width", `${width}%`);
    });
}

// Apply on page load
document.addEventListener("DOMContentLoaded", applyTimelinePositioning);

// Re-apply after htmx swaps content
document.addEventListener("htmx:afterSwap", applyTimelinePositioning);
