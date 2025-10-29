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

// Copy share URL to clipboard with visual feedback
async function copyShareUrl(button, traceId) {
  try {
    const shareUrl = button.getAttribute("data-share-url");

    // Copy to clipboard
    await navigator.clipboard.writeText(shareUrl);

    // Show success feedback on button
    const originalHTML = button.innerHTML;
    button.innerHTML =
      '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 16 16"><path d="M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z"/></svg>';
    button.classList.remove("bg-emerald-700", "hover:bg-emerald-600");
    button.classList.add("bg-green-600", "hover:bg-green-700");

    // Also flash the URL text
    const urlSpan = document.getElementById(`share-url-${traceId}`);
    if (urlSpan) {
      urlSpan.classList.add("text-green-400", "font-bold");
      setTimeout(() => {
        urlSpan.classList.remove("text-green-400", "font-bold");
      }, 2000);
    }

    setTimeout(() => {
      button.innerHTML = originalHTML;
      button.classList.remove("bg-green-600", "hover:bg-green-700");
      button.classList.add("bg-emerald-700", "hover:bg-emerald-600");
    }, 2000);
  } catch (error) {
    console.error("Failed to copy share URL:", error);
    alert("Failed to copy share URL. See console for details.");
  }
}

// Set up event delegation for copy share URL buttons
function setupCopyShareUrlHandlers() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-copy-share-url]");
    if (button) {
      event.preventDefault();
      const traceId = button.getAttribute("data-trace-id");
      copyShareUrl(button, traceId);
    }
  });
}

// Initialize on page load
document.addEventListener("DOMContentLoaded", setupCopyShareUrlHandlers);
