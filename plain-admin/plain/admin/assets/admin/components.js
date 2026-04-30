/*
 * `panel.style.{top,left}` mutations in initHovercard are a known CSP
 * carve-out — fluid positioning relative to a trigger's bounding rect
 * has no static-CSS equivalent until anchor-positioning ships in
 * Firefox. Tracked separately.
 */
(() => {
  const POPOVER_OPEN_EVENT = "plain-admin:popover-open";
  const POPOVER_SELECTOR = ".admin-popover, .admin-dropdown-menu";

  const registry = [];
  const register = (key, selector, init) => {
    const flag = `${key}Initialized`;
    const guardedSelector = `${selector}:not([data-${key.replace(/([A-Z])/g, "-$1").toLowerCase()}-initialized])`;
    const wrapped = (component) => {
      if (component.dataset[flag]) return;
      component.dataset[flag] = "true";
      init(component);
    };
    registry.push({ selector: guardedSelector, init: wrapped });
  };

  const initAll = (root) => {
    for (const { selector, init } of registry) {
      if (root.matches?.(selector)) init(root);
      root.querySelectorAll?.(selector).forEach(init);
    }
  };

  document.addEventListener("DOMContentLoaded", () => initAll(document));
  document.addEventListener("htmx:afterSwap", (evt) => initAll(evt.detail.target));

  // ---------- Shared popover lifecycle ----------
  // Open popovers are tracked in a Set so global outside-click and
  // cross-popover-close don't have to scan the whole document.
  const openComponents = new Set();

  const closePopover = (component, focusTrigger = true) => {
    const trigger = component.querySelector(":scope > button");
    if (!trigger || trigger.getAttribute("aria-expanded") !== "true") return false;
    const content = component.querySelector(":scope > [data-popover]");
    trigger.setAttribute("aria-expanded", "false");
    trigger.removeAttribute("aria-activedescendant");
    if (content) content.setAttribute("aria-hidden", "true");
    openComponents.delete(component);
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
    openComponents.add(component);
    return { trigger, content };
  };

  document.addEventListener("click", (event) => {
    if (!openComponents.size) return;
    const inside = event.target.closest(POPOVER_SELECTOR);
    for (const c of openComponents) {
      if (c !== inside) closePopover(c);
    }
  });

  document.addEventListener(POPOVER_OPEN_EVENT, (event) => {
    for (const c of openComponents) {
      if (c !== event.detail.source) closePopover(c, false);
    }
  });

  // ---------- Popover ----------

  const initPopover = (component) => {
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
  };
  register("popover", ".admin-popover", initPopover);

  // ---------- Dropdown menu (popover + keyboard menuitem nav) ----------

  const initDropdownMenu = (component) => {
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
  };
  register("dropdownMenu", ".admin-dropdown-menu", initDropdownMenu);

  // ---------- Tabs ----------

  const initTabs = (component) => {
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
  };
  register("tabs", ".admin-tabs", initTabs);

  // ---------- Segmented control (radiogroup of role=radio buttons) ----------

  const initSegmented = (component) => {
    const items = Array.from(component.querySelectorAll(':scope > [role="radio"]'));
    if (items.length === 0) return;

    const refreshTabindex = () => {
      const checked = items.find((i) => i.getAttribute("aria-checked") === "true");
      for (const item of items) {
        item.setAttribute("tabindex", item === checked ? "0" : "-1");
      }
    };
    refreshTabindex();

    component.addEventListener("click", (event) => {
      const target = event.target.closest('[role="radio"]');
      if (!target || !items.includes(target)) return;
      for (const item of items) {
        const expected = item === target ? "true" : "false";
        if (item.getAttribute("aria-checked") !== expected) {
          item.setAttribute("aria-checked", expected);
        }
      }
      refreshTabindex();
    });

    component.addEventListener("segmented:refresh", refreshTabindex);

    component.addEventListener("keydown", (event) => {
      const i = items.indexOf(event.target);
      if (i === -1) return;
      let next;
      switch (event.key) {
        case "ArrowRight":
        case "ArrowDown":
          next = items[(i + 1) % items.length];
          break;
        case "ArrowLeft":
        case "ArrowUp":
          next = items[(i - 1 + items.length) % items.length];
          break;
        case "Home":
          next = items[0];
          break;
        case "End":
          next = items[items.length - 1];
          break;
        default:
          return;
      }
      event.preventDefault();
      next.focus();
      next.click();
    });
  };
  register("segmented", ".admin-segmented", initSegmented);

  // ---------- Hovercard (Plain extension) ----------

  const initHovercard = (hovercard) => {
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
  };
  register("hovercard", ".admin-hovercard", initHovercard);
})();
