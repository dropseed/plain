/*!
 * Basecoat UI — sidebar.js (vendored)
 * https://github.com/hunvreus/basecoat — MIT License
 * Copyright (c) 2025 Ronan Berder
 */
(() => {
  const initSidebar = (sidebarComponent) => {
    const initialOpen = sidebarComponent.dataset.initialOpen !== "false";
    const initialMobileOpen = sidebarComponent.dataset.initialMobileOpen === "true";
    const breakpoint = parseInt(sidebarComponent.dataset.breakpoint) || 768;

    let open =
      breakpoint > 0
        ? window.innerWidth >= breakpoint
          ? initialOpen
          : initialMobileOpen
        : initialOpen;

    const updateState = () => {
      sidebarComponent.setAttribute("aria-hidden", !open);
      if (open) {
        sidebarComponent.removeAttribute("inert");
      } else {
        sidebarComponent.setAttribute("inert", "");
      }
    };

    const setState = (state) => {
      open = state;
      updateState();
    };

    const sidebarId = sidebarComponent.id;

    document.addEventListener("basecoat:sidebar", (event) => {
      if (event.detail?.id && event.detail.id !== sidebarId) return;

      switch (event.detail?.action) {
        case "open":
          setState(true);
          break;
        case "close":
          setState(false);
          break;
        default:
          setState(!open);
          break;
      }
    });

    sidebarComponent.addEventListener("click", (event) => {
      const target = event.target;
      const nav = sidebarComponent.querySelector("nav");

      const isMobile = window.innerWidth < breakpoint;

      if (
        isMobile &&
        target.closest("a, button") &&
        !target.closest("[data-keep-mobile-sidebar-open]")
      ) {
        if (document.activeElement) document.activeElement.blur();
        setState(false);
        return;
      }

      if (target === sidebarComponent || (nav && !nav.contains(target))) {
        if (document.activeElement) document.activeElement.blur();
        setState(false);
      }
    });

    updateState();
    sidebarComponent.dataset.sidebarInitialized = true;
    sidebarComponent.dispatchEvent(new CustomEvent("basecoat:initialized"));
  };

  if (window.basecoat) {
    window.basecoat.register("sidebar", ".sidebar:not([data-sidebar-initialized])", initSidebar);
  }
})();
