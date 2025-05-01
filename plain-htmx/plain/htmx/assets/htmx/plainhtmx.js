// Expect a data-csrftoken attribute on our own script tag
const csrfToken = document.currentScript.dataset.csrftoken;
const csrfHeader = document.currentScript.dataset.csrfheader;

htmx.on("htmx:configRequest", (event) => {
  // Custom header for Plain-HX-Action
  const actionElt = htmx.closest(event.detail.elt, "[plain-hx-action]");
  if (actionElt) {
    event.detail.headers["Plain-HX-Action"] =
      actionElt.getAttribute("plain-hx-action");
  }

  // Custom header for Plain-HX-Fragment
  const fragmentElt = htmx.closest(event.detail.elt, "[plain-hx-fragment]");
  if (fragmentElt) {
    event.detail.headers["Plain-HX-Fragment"] =
      fragmentElt.getAttribute("plain-hx-fragment");
  }

  // Add the CSRF token to all non-GET requests automatically
  if (event.detail.method !== "GET" && event.detail.verb !== "get") {
    event.detail.headers[csrfHeader] = csrfToken;
  }
});

htmx.defineExtension("error-classes", {
  onEvent: (name, evt) => {
    if (name === "htmx:beforeRequest") {
      // TODO use the value from hx-indicator
      const target = evt.detail.target;
      // Remove every class that starts with htmx-error
      for (let i = 0; i < target.classList.length; i++) {
        if (target.classList[i].startsWith("htmx-error-")) {
          target.classList.remove(target.classList[i]);
        }
      }
    }

    if (name === "htmx:responseError") {
      const target = evt.detail.target;
      htmx.addClass(target, "htmx-error-response");
      htmx.addClass(target, `htmx-error-response-${evt.detail.xhr.status}`);
    }

    if (name === "htmx:sendError") {
      const target = evt.detail.target;
      htmx.addClass(target, "htmx-error-send");
    }
  },
});

// Our own load event, to support lazy loading
// *after* our fragment extension is added.
// Use with hx-trigger="plainhtmx:load from:body"
// (this used to work without the timeout -- I'm not sure why there's a race condition now?)
setTimeout(() => {
  htmx.trigger(document.body, "plainhtmx:load");
}, 250);
