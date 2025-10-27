jQuery(($) => {
  // Sidebar toggle functionality with localStorage
  const STORAGE_KEY = "admin-sidebar-collapsed";
  const $sidebar = $("#admin-sidebar");

  // Click: persistent toggle
  $(document).on("click", "#sidebar-toggle", (e) => {
    e.preventDefault();
    const $html = $("html");
    const isCurrentlyCollapsed =
      $html.attr("data-sidebar-collapsed") === "true";
    const willBeCollapsed = !isCurrentlyCollapsed;

    if (willBeCollapsed) {
      $html.attr("data-sidebar-collapsed", "true");
    } else {
      $html.removeAttr("data-sidebar-collapsed");
    }
    localStorage.setItem(STORAGE_KEY, willBeCollapsed);
  });

  // Hover preview: show sidebar temporarily when collapsed
  let hoverTimeout;

  $(document).on("mouseenter", "#sidebar-toggle", () => {
    if ($("html").attr("data-sidebar-collapsed") === "true") {
      clearTimeout(hoverTimeout);
      $sidebar.attr("data-preview", "true");
    }
  });

  $(document).on("mouseleave", "#sidebar-toggle", () => {
    hoverTimeout = setTimeout(() => {
      if (!$sidebar.is(":hover")) {
        $sidebar.removeAttr("data-preview");
      }
    }, 100);
  });

  $(document).on("mouseenter", "#admin-sidebar", () => {
    clearTimeout(hoverTimeout);
  });

  $(document).on("mouseleave", "#admin-sidebar", () => {
    if ($("html").attr("data-sidebar-collapsed") === "true") {
      $sidebar.removeAttr("data-preview");
    }
  });

  // Use event delegation for HTMX compatibility
  $(document).on("click", "[data-toggle]", function (e) {
    e.preventDefault();
    const targets = $(this).data("toggle").split(",");
    $.each(targets, (_index, target) => {
      const $target = $(target);
      if ($target.data("toggle-class")) {
        $target.toggleClass($target.data("toggle-class"));
      } else {
        $target.toggle();
      }
    });
  });

  $(document).on("change", "[data-autosubmit]", function (_e) {
    $(this).closest("form").submit();
  });

  function createDropdowns(target) {
    $(target)
      .find("[data-dropdown]")
      .each(function () {
        const template = this.querySelector("template");
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

  function createTooltips(target) {
    $(target)
      .find("[data-tooltip]")
      .each(function () {
        tippy(this, {
          content: this.dataset.tooltip,
          duration: 100,
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
  createTooltips(document);
  autolinkColumns(document);

  // Search uses htmx to load elements,
  // so we need to hook those up too.
  htmx.on("htmx:afterSwap", (evt) => {
    createDropdowns(evt.detail.target);
    createTooltips(evt.detail.target);
    autolinkColumns(evt.detail.target);
    updateActiveNav();
  });

  // Navigation section toggle with accordion behavior
  $(document).on("click", "[data-nav-toggle]", function (e) {
    e.preventDefault();
    const sectionId = $(this).data("nav-toggle");
    const $section = $(`#${sectionId}`);
    const $svg = $(this).find("svg").last();
    const isCurrentlyOpen = $section.is(":visible");

    // Close all other sections in the same nav area
    const navArea = $(this).closest("div").find("[data-nav-toggle]");
    navArea.each(function () {
      const otherSectionId = $(this).data("nav-toggle");
      const $otherSection = $(`#${otherSectionId}`);
      const $otherSvg = $(this).find("svg").last();

      if (otherSectionId !== sectionId) {
        $otherSection.slideUp(80);
        $otherSvg.removeClass("rotate-180");
      }
    });

    // Toggle the clicked section
    if (isCurrentlyOpen) {
      $section.slideUp(80);
      $svg.removeClass("rotate-180");
    } else {
      $section.slideDown(80);
      $svg.addClass("rotate-180");
    }
  });

  function updateActiveNav() {
    const currentPath = window.location.pathname;

    // Remove all active states
    $("#admin-sidebar [data-active]").removeAttr("data-active");

    // Add active state to matching link
    $(`#admin-sidebar a[href="${currentPath}"]`).attr("data-active", "true");
  }

  window.addEventListener("popstate", updateActiveNav); // Update on browser back/forward

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
});
