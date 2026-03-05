// Observer JS - CSP-compliant timeline positioning and utilities

// Apply CSS custom properties for timeline positioning
function applyTimelinePositioning() {
  document.querySelectorAll("[data-start-percent][data-width-percent]").forEach((el) => {
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

// Copy JSON to clipboard with visual feedback
async function copyJson(button) {
  const jsonUrl = button.getAttribute("data-json-url");
  const originalHTML = button.innerHTML;

  try {
    // Fetch the JSON data
    const response = await fetch(jsonUrl);
    const data = await response.json();
    const jsonText = JSON.stringify(data, null, 2);

    // Copy to clipboard
    await navigator.clipboard.writeText(jsonText);

    // Show success feedback
    button.innerHTML =
      '<svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 16 16"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg><span>Copied!</span>';
    button.classList.remove("bg-white/10", "hover:bg-white/20");
    button.classList.add("bg-green-600", "hover:bg-green-700", "text-white");

    setTimeout(() => {
      button.innerHTML = originalHTML;
      button.classList.remove("bg-green-600", "hover:bg-green-700", "text-white");
      button.classList.add("bg-white/10", "hover:bg-white/20");
    }, 2000);
  } catch (error) {
    console.error("Failed to copy JSON:", error);
    button.innerHTML =
      '<svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 16 16"><path d="M8 15A7 7 0 1 1 8 1a7 7 0 0 1 0 14zm0 1A8 8 0 1 0 8 0a8 8 0 0 0 0 16z"/><path d="M7.002 11a1 1 0 1 1 2 0 1 1 0 0 1-2 0zM7.1 4.995a.905.905 0 1 1 1.8 0l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 4.995z"/></svg><span>Error</span>';
    button.classList.remove("bg-white/10", "hover:bg-white/20");
    button.classList.add("bg-red-600", "hover:bg-red-700", "text-white");

    setTimeout(() => {
      button.innerHTML = originalHTML;
      button.classList.remove("bg-red-600", "hover:bg-red-700", "text-white");
      button.classList.add("bg-white/10", "hover:bg-white/20");
    }, 2000);
  }
}

// Set up event delegation for copy JSON buttons
document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-copy-json]");
  if (button) {
    event.preventDefault();
    copyJson(button);
  }
});
