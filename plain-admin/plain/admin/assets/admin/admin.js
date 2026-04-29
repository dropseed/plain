/*
 * Admin chrome — global keybindings and HTMX network-error reporting.
 * Anything declarative (data-*) lives in behaviors/.
 */
jQuery(($) => {
  htmx.on("htmx:responseError", (evt) => {
    const status = evt.detail.xhr.status;
    const statusText = evt.detail.xhr.statusText;
    let message = `Request failed: HTTP ${status} ${statusText}`;

    try {
      const contentType = evt.detail.xhr.getResponseHeader("content-type");
      if (contentType?.includes("application/json")) {
        const response = JSON.parse(evt.detail.xhr.responseText);
        if (response.error || response.message) {
          message = response.error || response.message;
        }
      }
    } catch {
      // Ignore JSON parsing errors, use default message
    }

    alert(message);
  });

  htmx.on("htmx:sendError", (_evt) => {
    alert("Network error: Could not connect to server");
  });

  htmx.on("htmx:timeout", (_evt) => {
    alert("Request timed out");
  });

  // "/" focuses the topbar search.
  $(document).on("keydown", (e) => {
    const activeTag = document.activeElement.tagName;
    const isEditable = document.activeElement.isContentEditable;
    if (e.key === "/" && !["INPUT", "TEXTAREA", "SELECT"].includes(activeTag) && !isEditable) {
      e.preventDefault();
      $("#topbar-search").trigger("focus");
    }
  });
});
