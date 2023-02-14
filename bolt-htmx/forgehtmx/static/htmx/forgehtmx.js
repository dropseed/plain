// Expect a data-csrftoken attribute on our own script tag
var csrfToken = document.currentScript.dataset.csrftoken;

htmx.on("htmx:configRequest", function (event) {
  // Custom header for FHX-Action
  var actionElt = htmx.closest(event.detail.elt, "[fhx-action]");
  if (actionElt) {
    event.detail.headers["FHX-Action"] = actionElt.getAttribute("fhx-action");
  }

  // Custom header for FHX-Fragment
  var fragmentElt = htmx.closest(event.detail.elt, "[fhx-fragment]");
  if (fragmentElt) {
    event.detail.headers["FHX-Fragment"] =
      fragmentElt.getAttribute("fhx-fragment");
  }

  // Add the CSRF token to all non-GET requests automatically
  if (event.detail.method !== "GET" && event.detail.verb !== "get") {
    event.detail.headers["X-CSRFToken"] = csrfToken;
  }
});

htmx.defineExtension("error-classes", {
  onEvent: function (name, evt) {
    if (name === "htmx:beforeRequest") {
      // TODO use the value from hx-indicator
      var target = evt.detail.target;
      // Remove every class that starts with htmx-error
      for (var i = 0; i < target.classList.length; i++) {
        if (target.classList[i].startsWith("htmx-error-")) {
          target.classList.remove(target.classList[i]);
        }
      }
    }

    if (name === "htmx:responseError") {
      var target = evt.detail.target;
      htmx.addClass(target, "htmx-error-response");
      htmx.addClass(target, "htmx-error-response-" + evt.detail.xhr.status);
    }

    if (name === "htmx:sendError") {
      var target = evt.detail.target;
      htmx.addClass(target, "htmx-error-send");
    }
  },
});

// Our own load event, to support lazy loading
// *after* our fragment extension is added
htmx.trigger(document.body, "fhxLoad");
