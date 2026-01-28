jQuery(($) => {
  // Submit forms via GET, excluding empty params from the URL
  function submitFormClean(form) {
    const formData = new FormData(form);
    const params = new URLSearchParams();
    for (const [key, value] of formData.entries()) {
      if (value) {
        params.append(key, value);
      }
    }
    // Use form action if set, otherwise current path
    const basePath = form.getAttribute("action") || window.location.pathname;
    const url = params.toString()
      ? `${basePath}?${params.toString()}`
      : basePath;
    window.location.href = url;
  }

  $(document).on("change", "[data-autosubmit]", function (_e) {
    submitFormClean($(this).closest("form")[0]);
  });

  // Also handle regular form submissions in the list header
  $(document).on("submit", "form[method='GET']", function (e) {
    e.preventDefault();
    submitFormClean(this);
  });

  function createDropdowns(target) {
    $(target)
      .find("[data-dropdown]")
      .each(function () {
        const template = this.querySelector("template");
        if (!template) return; // Skip if no template found
        tippy(this, {
          content: template.innerHTML,
          trigger: "click",
          allowHTML: true,
          interactive: true,
          duration: 100,
          placement: "bottom-end",
          offset: [0, 6],
          arrow: false,
          appendTo: () => document.body,
          onCreate: (instance) => {
            instance.popper.classList.add("*:bg-white");
            instance.popper.classList.add("*:w-48");
            instance.popper.classList.add("*:rounded-md");
            instance.popper.classList.add("*:shadow-lg");
            instance.popper.classList.add("*:ring-1");
            instance.popper.classList.add("*:ring-stone-200");
          },
        });
      });
  }

  function autolinkColumns(target) {
    $(target)
      .find("[data-column-autolink]")
      .each(function () {
        const $this = $(this);
        if ($this.find("a").length > 0) {
          // Column already has a link, so don't add another
          return;
        }
        const autolinkUrl = $this.data("column-autolink");
        if (!autolinkUrl) {
          // No URL, so don't add a link
          return;
        }
        const $link = $(document.createElement("a"));
        $link.attr("href", autolinkUrl);
        $link.addClass("flex p-2 -m-2 text-black/90 hover:no-underline");
        $(this).wrapInner($link);
      });
  }

  createDropdowns(document);
  autolinkColumns(document);

  // Search uses htmx to load elements,
  // so we need to hook those up too.
  htmx.on("htmx:afterSwap", (evt) => {
    createDropdowns(evt.detail.target);
    autolinkColumns(evt.detail.target);
  });

  // HTMX error handling
  htmx.on("htmx:responseError", (evt) => {
    const status = evt.detail.xhr.status;
    const statusText = evt.detail.xhr.statusText;
    let message = `Request failed: HTTP ${status} ${statusText}`;

    // Try to get more specific error message from response
    try {
      const contentType = evt.detail.xhr.getResponseHeader("content-type");
      if (contentType?.includes("application/json")) {
        const response = JSON.parse(evt.detail.xhr.responseText);
        if (response.error || response.message) {
          message = response.error || response.message;
        }
      }
    } catch (_e) {
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

  // Global search keyboard shortcut
  $(document).on("keydown", (e) => {
    const activeTag = document.activeElement.tagName;
    const isEditable = document.activeElement.isContentEditable;
    if (
      e.key === "/" &&
      !["INPUT", "TEXTAREA", "SELECT"].includes(activeTag) &&
      !isEditable
    ) {
      e.preventDefault();
      $("#topbar-search").trigger("focus");
    }
  });
});
