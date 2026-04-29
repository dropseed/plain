/*
 * Plain admin — interactive UI components.
 *
 * Forked from Basecoat UI (MIT — see styles/ATTRIBUTIONS.md). Consolidated
 * into one file with a Plain-shaped lifecycle: init runs on DOMContentLoaded
 * and after every htmx:afterSwap, idempotent via per-instance data-* flags.
 *
 * Outside-click and cross-popover-close are dispatched by TWO global
 * document listeners (not per-instance) so HTMX swaps that destroy and
 * recreate popovers don't leak listeners.
 *
 * `panel.style.{top,left}` mutations in initHovercard are a known CSP
 * carve-out — fluid positioning relative to a trigger's bounding rect
 * has no static-CSS equivalent until anchor-positioning ships in
 * Firefox. Tracked separately.
 */
(() => {
  const POPOVER_OPEN_EVENT = "plain-admin:popover-open";
  const POPOVER_SELECTOR = ".popover, .dropdown-menu";

  const registry = [];
  const register = (selector, init) => registry.push({ selector, init });

  const initAll = () => {
    for (const { selector, init } of registry) {
      document.querySelectorAll(selector).forEach(init);
    }
  };

  document.addEventListener("DOMContentLoaded", initAll);
  document.addEventListener("htmx:afterSwap", initAll);

  // ---------- Shared popover lifecycle ----------

  const closePopover = (component, focusTrigger = true) => {
    const trigger = component.querySelector(":scope > button");
    if (!trigger || trigger.getAttribute("aria-expanded") !== "true") return false;
    const content = component.querySelector(":scope > [data-popover]");
    trigger.setAttribute("aria-expanded", "false");
    trigger.removeAttribute("aria-activedescendant");
    if (content) content.setAttribute("aria-hidden", "true");
    if (focusTrigger) trigger.focus();
    return true;
  };

  const openPopover = (component) => {
    const trigger = component.querySelector(":scope > button");
    const content = component.querySelector(":scope > [data-popover]");
    if (!trigger || !content) return null;
    document.dispatchEvent(new CustomEvent(POPOVER_OPEN_EVENT, { detail: { source: component } }));
    trigger.setAttribute("aria-expanded", "true");
    content.setAttribute("aria-hidden", "false");
    return { trigger, content };
  };

  // Global delegated listeners — attached once, never per instance.
  document.addEventListener("click", (event) => {
    document.querySelectorAll(POPOVER_SELECTOR).forEach((c) => {
      if (!c.contains(event.target)) closePopover(c);
    });
  });

  document.addEventListener(POPOVER_OPEN_EVENT, (event) => {
    document.querySelectorAll(POPOVER_SELECTOR).forEach((c) => {
      if (c !== event.detail.source) closePopover(c, false);
    });
  });

  // ---------- Popover ----------

  const initPopover = (component) => {
    if (component.dataset.popoverInitialized) return;
    const trigger = component.querySelector(":scope > button");
    const content = component.querySelector(":scope > [data-popover]");
    if (!trigger || !content) {
      console.error("Popover init failed: missing trigger or [data-popover]", component);
      return;
    }

    trigger.addEventListener("click", () => {
      if (trigger.getAttribute("aria-expanded") === "true") {
        closePopover(component);
      } else {
        openPopover(component);
        const auto = content.querySelector("[autofocus]");
        if (auto) {
          content.addEventListener("transitionend", () => auto.focus(), { once: true });
        }
      }
    });

    component.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closePopover(component);
    });

    component.dataset.popoverInitialized = "true";
  };
  register(".popover:not([data-popover-initialized])", initPopover);

  // ---------- Dropdown menu (popover + keyboard menuitem nav) ----------

  const initDropdownMenu = (component) => {
    if (component.dataset.dropdownMenuInitialized) return;
    const trigger = component.querySelector(":scope > button");
    const popover = component.querySelector(":scope > [data-popover]");
    const menu = popover?.querySelector('[role="menu"]');
    if (!trigger || !popover || !menu) {
      console.error(
        "Dropdown menu init failed: missing trigger / [data-popover] / [role=menu]",
        component,
      );
      return;
    }

    let menuItems = [];
    let activeIndex = -1;

    const setActiveItem = (index) => {
      if (activeIndex > -1) menuItems[activeIndex]?.classList.remove("active");
      activeIndex = index;
      if (activeIndex > -1) {
        const active = menuItems[activeIndex];
        active.classList.add("active");
        trigger.setAttribute("aria-activedescendant", active.id);
      } else {
        trigger.removeAttribute("aria-activedescendant");
      }
    };

    const close = (focusTrigger = true) => {
      if (closePopover(component, focusTrigger)) setActiveItem(-1);
    };

    const open = (initialSelection) => {
      openPopover(component);
      menuItems = Array.from(menu.querySelectorAll('[role^="menuitem"]')).filter(
        (i) => !i.hasAttribute("disabled") && i.getAttribute("aria-disabled") !== "true",
      );
      if (menuItems.length && initialSelection) {
        setActiveItem(initialSelection === "first" ? 0 : menuItems.length - 1);
      }
    };

    trigger.addEventListener("click", () => {
      if (trigger.getAttribute("aria-expanded") === "true") close();
      else open();
    });

    component.addEventListener("keydown", (event) => {
      const isOpen = trigger.getAttribute("aria-expanded") === "true";

      if (event.key === "Escape") {
        if (isOpen) close();
        return;
      }

      if (!isOpen) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          open();
        } else if (event.key === "ArrowDown") {
          event.preventDefault();
          open("first");
        } else if (event.key === "ArrowUp") {
          event.preventDefault();
          open("last");
        }
        return;
      }

      if (!menuItems.length) return;

      let next = activeIndex;
      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          next = activeIndex === -1 ? 0 : Math.min(activeIndex + 1, menuItems.length - 1);
          break;
        case "ArrowUp":
          event.preventDefault();
          next = activeIndex === -1 ? menuItems.length - 1 : Math.max(activeIndex - 1, 0);
          break;
        case "Home":
          event.preventDefault();
          next = 0;
          break;
        case "End":
          event.preventDefault();
          next = menuItems.length - 1;
          break;
        case "Enter":
        case " ":
          event.preventDefault();
          menuItems[activeIndex]?.click();
          close();
          return;
      }
      if (next !== activeIndex) setActiveItem(next);
    });

    menu.addEventListener("mousemove", (event) => {
      const item = event.target.closest('[role^="menuitem"]');
      if (!item) return;
      const i = menuItems.indexOf(item);
      if (i !== -1 && i !== activeIndex) setActiveItem(i);
    });

    menu.addEventListener("mouseleave", () => setActiveItem(-1));

    menu.addEventListener("click", (event) => {
      if (event.target.closest('[role^="menuitem"]')) close();
    });

    component.dataset.dropdownMenuInitialized = "true";
  };
  register(".dropdown-menu:not([data-dropdown-menu-initialized])", initDropdownMenu);

  // ---------- Tabs ----------

  const initTabs = (component) => {
    if (component.dataset.tabsInitialized) return;
    const tablist = component.querySelector('[role="tablist"]');
    if (!tablist) return;

    const tabs = Array.from(tablist.querySelectorAll('[role="tab"]'));
    const panels = tabs
      .map((tab) => document.getElementById(tab.getAttribute("aria-controls")))
      .filter(Boolean);

    const selectTab = (tabToSelect) => {
      tabs.forEach((tab, index) => {
        tab.setAttribute("aria-selected", "false");
        tab.setAttribute("tabindex", "-1");
        if (panels[index]) panels[index].hidden = true;
      });
      tabToSelect.setAttribute("aria-selected", "true");
      tabToSelect.setAttribute("tabindex", "0");
      const activePanel = document.getElementById(tabToSelect.getAttribute("aria-controls"));
      if (activePanel) activePanel.hidden = false;
    };

    tablist.addEventListener("click", (event) => {
      const clicked = event.target.closest('[role="tab"]');
      if (clicked) selectTab(clicked);
    });

    tablist.addEventListener("keydown", (event) => {
      const current = event.target;
      if (!tabs.includes(current)) return;
      const i = tabs.indexOf(current);
      let next;
      switch (event.key) {
        case "ArrowRight":
          next = tabs[(i + 1) % tabs.length];
          break;
        case "ArrowLeft":
          next = tabs[(i - 1 + tabs.length) % tabs.length];
          break;
        case "Home":
          next = tabs[0];
          break;
        case "End":
          next = tabs[tabs.length - 1];
          break;
        default:
          return;
      }
      event.preventDefault();
      selectTab(next);
      next.focus();
    });

    component.dataset.tabsInitialized = "true";
  };
  register(".tabs:not([data-tabs-initialized])", initTabs);

  // ---------- Hovercard (Plain extension) ----------

  const initHovercard = (hovercard) => {
    if (hovercard.dataset.hovercardInitialized) return;
    const panel = hovercard.querySelector(":scope > [data-hovercard]");
    const trigger = Array.from(hovercard.children).find((c) => c !== panel);
    if (!trigger || !panel) {
      console.error("Hovercard init failed: missing trigger or [data-hovercard]", hovercard);
      return;
    }

    let hideTimeout;
    const show = () => {
      clearTimeout(hideTimeout);
      hovercard.dispatchEvent(new CustomEvent("hovercard:show"));
      const rect = trigger.getBoundingClientRect();
      panel.style.top = `${rect.bottom + 4}px`;
      panel.style.left = `${rect.left}px`;
      panel.setAttribute("aria-hidden", "false");
    };
    const hide = () => {
      hideTimeout = setTimeout(() => panel.setAttribute("aria-hidden", "true"), 100);
    };

    trigger.addEventListener("mouseenter", show);
    trigger.addEventListener("mouseleave", hide);
    panel.addEventListener("mouseenter", show);
    panel.addEventListener("mouseleave", hide);

    hovercard.dataset.hovercardInitialized = "true";
  };
  register(".hovercard:not([data-hovercard-initialized])", initHovercard);
})();
