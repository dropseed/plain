(() => {
  htmx.defineExtension("plain-views", {
    init() {
      // Set or append this extension to the body hx-ext automatically
      const body = document.querySelector("body");
      if (body) {
        const ext = body.getAttribute("hx-ext") || "";
        if (!ext.includes("plain-views")) {
          body.setAttribute("hx-ext", `${ext},plain-views`);
        }
      }
    },
    onEvent(name, evt) {
      if (name === "htmx:configRequest") {
        const { elt, headers } = evt.detail;

        const actionElt = htmx.closest(elt, "[plain-hx-action]");
        const fragmentElt = htmx.closest(elt, "[plain-hx-fragment]");

        if (actionElt)
          headers["Plain-HX-Action"] =
            actionElt.getAttribute("plain-hx-action");
        if (fragmentElt)
          headers["Plain-HX-Fragment"] =
            fragmentElt.getAttribute("plain-hx-fragment");
      }
    },
  });

  htmx.defineExtension("plain-errors", {
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
})();
