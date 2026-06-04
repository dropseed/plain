// window.plainToolbar is exposed for the JS console (hide/show, etc.).
window.plainToolbar = window.plainToolbar || {
  // State mirrors the data-* attributes on #plaintoolbar.
  expanded: false,
  collapsed: true,
  position: "left",
  itemsOpen: false,

  el: () => document.getElementById("plaintoolbar"),
  bar: () => document.getElementById("plaintoolbar-bar"),

  hide: function () {
    this.el()?.setAttribute("data-hidden", "");
    this.syncBodyState();
  },
  show: function () {
    localStorage.removeItem("plaintoolbar.hidden_until");
    this.el()?.removeAttribute("data-hidden");
    this.syncBodyState();
  },
  shouldHide: () => {
    const until = localStorage.getItem("plaintoolbar.hidden_until");
    if (until && Date.now() < Number(until)) return true;
    if (until) localStorage.removeItem("plaintoolbar.hidden_until");
    return false;
  },
  hideUntil: function (until) {
    localStorage.setItem("plaintoolbar.hidden_until", until);
    this.hide();
  },

  // --- Details panel --------------------------------------------------------
  setExpanded: function (expanded, persist = true) {
    this.expanded = expanded;
    this.el().dataset.expanded = expanded ? "true" : "false";
    if (persist) {
      localStorage.setItem("plaintoolbar.expanded", expanded ? "1" : "0");
    }
  },
  expand: function () {
    this.setExpanded(true);
  },
  collapse: function () {
    this.setExpanded(false);
  },
  toggleExpand: function () {
    this.setExpanded(!this.expanded);
  },

  // --- Bar: collapsed pill vs. full-width bar -------------------------------
  setCollapsed: function (collapsed, persist = true) {
    this.collapsed = collapsed;
    this.el().dataset.collapsed = collapsed ? "true" : "false";
    // Docking/undocking is instant — only a snap or cycle animates the pill.
    this.bar()?.removeAttribute("data-animate");
    if (persist) {
      localStorage.setItem("plaintoolbar.bar_collapsed", collapsed ? "1" : "0");
    }
    this.syncBodyState();
  },

  // --- Pill position --------------------------------------------------------
  // The three positions are pure CSS (translateX); flipping data-position with
  // data-animate set lets the browser do the slide.
  setPosition: function (position, persist = true) {
    this.position = position;
    this.el().dataset.position = position;
    if (persist) {
      localStorage.setItem("plaintoolbar.position", position);
    }
  },
  cyclePosition: function () {
    const order = ["left", "center", "right"];
    this.bar()?.setAttribute("data-animate", "");
    this.setPosition(order[(order.indexOf(this.position) + 1) % order.length]);
  },

  // --- Mobile items dropdown ------------------------------------------------
  setItemsOpen: function (open) {
    this.itemsOpen = open;
    this.el().dataset.itemsOpen = open ? "true" : "false";
  },

  // --- Tabs -----------------------------------------------------------------
  // Switch which tab's content is visible. Pure: no effect on collapse/expand.
  selectTab: function (tabName, persist = true) {
    const toolbar = this.el();
    const tab = toolbar.querySelector(`div[data-toolbar-tab="${CSS.escape(tabName)}"]`);
    if (!tab) {
      console.warn(`Toolbar tab ${tabName} does not exist`);
      return;
    }
    for (const child of tab.parentNode.children) {
      child.classList.toggle("hidden", child !== tab);
    }
    for (const btn of toolbar.querySelectorAll("button[data-toolbar-tab]")) {
      btn.toggleAttribute("data-active", btn.dataset.toolbarTab === tabName);
    }
    if (persist) {
      localStorage.setItem("plaintoolbar.tab", tabName);
    }
  },
  // Reveal a tab: dock the bar (visually, not persisted) and open the panel.
  showTab: function (tabName) {
    this.setCollapsed(false, false);
    this.expand();
    this.selectTab(tabName);
  },

  setHeight: (height) => {
    // Inline style: the panel height is a continuous drag value with no class
    // equivalent. CSP permits CSSOM property setters — only style="" attributes
    // and <style> tags are restricted.
    const content = document.querySelector("#plaintoolbar-details > div.overflow-auto");
    if (content) content.style.height = height;
  },
  resetHeight: function () {
    this.setHeight("");
    localStorage.removeItem("plaintoolbar.height");
  },

  // Reflect whether the full-width bar is showing onto <body>, so host layouts
  // (e.g. the admin) reserve space only when it's needed.
  syncBodyState: function () {
    const t = this.el();
    const visible = t && !t.hasAttribute("data-hidden");
    const fullBar = !!visible && !this.collapsed && window.matchMedia("(min-width: 640px)").matches;
    document.body.toggleAttribute("data-toolbar-fullbar", fullBar);
  },
};

// Hide immediately if the user dismissed the toolbar earlier.
if (window.plainToolbar.shouldHide()) {
  window.plainToolbar.hide();
}

function initToolbar() {
  const plainToolbar = window.plainToolbar;
  const toolbar = plainToolbar.el();
  if (!toolbar || plainToolbar._initialized) return;
  plainToolbar._initialized = true;

  const isDesktop = () => window.matchMedia("(min-width: 640px)").matches;

  // --- Restore persisted state ---------------------------------------------
  // Restoring is silent — only real user input writes to localStorage.
  plainToolbar.setPosition(localStorage.getItem("plaintoolbar.position") || "left", false);
  // Default (no saved value) is the collapsed pill.
  plainToolbar.setCollapsed(localStorage.getItem("plaintoolbar.bar_collapsed") !== "0", false);
  plainToolbar.setExpanded(localStorage.getItem("plaintoolbar.expanded") === "1", false);
  const savedTab = localStorage.getItem("plaintoolbar.tab");
  if (savedTab) plainToolbar.selectTab(savedTab);
  const savedHeight = localStorage.getItem("plaintoolbar.height");
  if (savedHeight) plainToolbar.setHeight(savedHeight);

  // An exception forces the toolbar fully open — temporary, not persisted.
  if (toolbar.querySelector('[data-toolbar-tab="Exception"]')) {
    plainToolbar.show();
    plainToolbar.setCollapsed(false, false);
    plainToolbar.setExpanded(true, false);
    plainToolbar.selectTab("Exception", false);
  }
  plainToolbar.syncBodyState();

  // --- Click handling (delegated) ------------------------------------------
  toolbar.addEventListener("click", (e) => {
    const tabBtn = e.target.closest("button[data-toolbar-tab]");
    if (tabBtn) {
      plainToolbar.setItemsOpen(false);
      // Clicking the active tab while the panel is open closes the panel.
      if (plainToolbar.expanded && tabBtn.hasAttribute("data-active")) {
        plainToolbar.collapse();
      } else {
        plainToolbar.showTab(tabBtn.dataset.toolbarTab);
      }
    } else if (e.target.closest("[data-plaintoolbar-hide]")) {
      plainToolbar.hide();
    } else if (e.target.closest("[data-plaintoolbar-hideuntil]")) {
      console.log("Hiding toolbar for 1 hour");
      plainToolbar.hideUntil(Date.now() + 3600000);
    } else if (e.target.closest("[data-plaintoolbar-expand]")) {
      plainToolbar.toggleExpand();
    } else if (e.target.closest("[data-plaintoolbar-collapse]")) {
      plainToolbar.setCollapsed(true);
    } else if (e.target.closest("#plaintoolbar-version")) {
      // Desktop pill: dock the bare bar. Mobile: toggle the items dropdown.
      if (isDesktop()) {
        plainToolbar.setCollapsed(false);
        plainToolbar.collapse();
      } else {
        plainToolbar.setItemsOpen(!plainToolbar.itemsOpen);
      }
    }
  });

  // Outside-click dismiss for the mobile items dropdown.
  document.addEventListener("click", (e) => {
    if (plainToolbar.itemsOpen && !toolbar.contains(e.target)) {
      plainToolbar.setItemsOpen(false);
    }
  });

  // --- Drag the collapsed pill to reposition it ----------------------------
  // During a drag the pill follows the pointer via an inline transform (no
  // transition). On release, data-animate is set and data-position flipped so
  // the CSS transition slides it to the snapped third.
  const bar = plainToolbar.bar();
  if (bar) {
    const THRESHOLD = 4;
    let drag = null; // { startX, fromX, width, moved }
    let suppressClick = false;

    const pointer = (e) => (e.touches && e.touches[0]) || e;
    const isPill = () => !(plainToolbar.collapsed === false && isDesktop());

    const onDown = (e) => {
      suppressClick = false;
      if (!isPill()) return;
      const rect = bar.getBoundingClientRect();
      drag = {
        startX: pointer(e).clientX,
        fromX: rect.left,
        width: rect.width,
        moved: false,
      };
    };

    const endDrag = () => {
      if (!drag) return;
      const moved = drag.moved;
      drag = null;
      if (!moved) return;
      // Snap to the third of the viewport the pill's center landed in.
      const rect = bar.getBoundingClientRect();
      const center = rect.left + rect.width / 2;
      const w = window.innerWidth;
      const position = center >= (2 * w) / 3 ? "right" : center >= w / 3 ? "center" : "left";
      bar.setAttribute("data-animate", ""); // arm the CSS slide
      plainToolbar.setPosition(position); // data-position drives the target
      bar.style.transform = ""; // drop the inline override -> CSS animates
      document.body.classList.remove("select-none");
      suppressClick = true;
      // Clear on the next task in case no click follows the drag (released
      // off-bar, touch, cancelled gesture) — a stale flag would otherwise
      // swallow a later keyboard activation.
      setTimeout(() => {
        suppressClick = false;
      }, 0);
    };

    const onMove = (e) => {
      if (!drag) return;
      // A mouse drag whose button was released off-window never delivers a
      // mouseup — end the drag if no button is held anymore.
      if (e.type === "mousemove" && e.buttons === 0) {
        endDrag();
        return;
      }
      const dx = pointer(e).clientX - drag.startX;
      if (!drag.moved && Math.abs(dx) < THRESHOLD) return;
      if (!drag.moved) {
        drag.moved = true;
        bar.removeAttribute("data-animate"); // 1:1 tracking — no transition
        document.body.classList.add("select-none");
      }
      const x = Math.max(0, Math.min(window.innerWidth - drag.width, drag.fromX + dx));
      bar.style.transform = `translateX(${x}px)`;
      e.preventDefault();
    };

    bar.addEventListener("mousedown", onDown);
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", endDrag);
    bar.addEventListener("touchstart", onDown, { passive: true });
    document.addEventListener("touchmove", onMove, { passive: false });
    document.addEventListener("touchend", endDrag);
    document.addEventListener("touchcancel", endDrag);

    // Swallow the click that fires right after a drag so the release doesn't
    // also activate a button inside the pill.
    bar.addEventListener(
      "click",
      (e) => {
        if (suppressClick) {
          suppressClick = false;
          e.stopPropagation();
          e.preventDefault();
        }
      },
      true,
    );
  }

  // --- Keep state in sync across viewport changes --------------------------
  window.addEventListener("resize", () => {
    // Desktop has no items dropdown; close it so it can't reappear if the
    // viewport later crosses back below the breakpoint.
    if (isDesktop()) plainToolbar.setItemsOpen(false);
    plainToolbar.syncBodyState();
  });

  // --- Manual resize of the expanded panel via its drag handle -------------
  const details = document.getElementById("plaintoolbar-details");
  const handle = details && details.querySelector("[data-resizer]");
  const content = handle && handle.nextElementSibling;
  if (handle && content) {
    let startY = 0;
    let startHeight = 0;
    let currentHeight = null;
    const onResizeMove = (e) => {
      const newHeight = Math.max(
        50,
        Math.min(window.innerHeight - 100, startHeight - (e.clientY - startY)),
      );
      currentHeight = `${newHeight}px`;
      plainToolbar.setHeight(currentHeight);
    };
    const onResizeEnd = () => {
      handle.classList.replace("cursor-grabbing", "cursor-grab");
      document.body.classList.remove("select-none");
      document.removeEventListener("mousemove", onResizeMove);
      document.removeEventListener("mouseup", onResizeEnd);
      if (currentHeight) {
        localStorage.setItem("plaintoolbar.height", currentHeight);
      }
    };
    handle.addEventListener("mousedown", (e) => {
      startY = e.clientY;
      startHeight = content.offsetHeight;
      handle.classList.replace("cursor-grab", "cursor-grabbing");
      document.body.classList.add("select-none");
      document.addEventListener("mousemove", onResizeMove);
      document.addEventListener("mouseup", onResizeEnd);
      e.preventDefault();
    });
  }
}

// The script is deferred, so the DOM is already parsed when it runs. Initialize
// immediately (rather than on `load`) so restored state is applied before first
// paint — no pill-to-bar flash, no admin layout shift.
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initToolbar);
} else {
  initToolbar();
}
