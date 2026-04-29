/*
 * HTMX network-error reporting — surfaces failed requests as alerts so
 * silent network/server errors don't leave the admin in a confused
 * state. Tries to extract a useful message from JSON error responses
 * before falling back to the generic HTTP status line.
 */
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
