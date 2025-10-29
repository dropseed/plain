// Make this available to the JS console for the user
window.plainToolbar = window.plainToolbar || {
  hide: () => {
    // Hide by setting style directly for CSP compliance
    const toolbar = document.getElementById("plaintoolbar");
    if (toolbar) {
      toolbar.style.display = "none";
    }
  },
  show: () => {
    localStorage.removeItem("plaintoolbar.hidden_until");
    const toolbar = document.getElementById("plaintoolbar");
    if (toolbar) {
      toolbar.style.display = "";
    }
  },
  shouldHide: () => {
    const hiddenUntil = localStorage.getItem("plaintoolbar.hidden_until");
    if (hiddenUntil) {
      if (Date.now() < hiddenUntil) {
        return true;
      }
      localStorage.removeItem("plaintoolbar.hidden_until");
      return false;
    }
    return false;
  },
  hideUntil: function (until) {
    localStorage.setItem("plaintoolbar.hidden_until", until);
    this.hide();
  },
  toggleExpand: function () {
    this.expanded = !this.expanded;
    document.querySelector("#plaintoolbar-details").classList.toggle("hidden");
    localStorage.setItem("plaintoolbar.expanded", this.expanded ? "1" : "0");
  },
  expand: function () {
    this.expanded = true;
    document.querySelector("#plaintoolbar-details").classList.remove("hidden");
    localStorage.setItem("plaintoolbar.expanded", "1");
  },
  collapse: function () {
    this.expanded = false;
    document.querySelector("#plaintoolbar-details").classList.add("hidden");
    localStorage.setItem("plaintoolbar.expanded", "0");
  },
  expandTemporary: function () {
    this.expanded = true;
    document.querySelector("#plaintoolbar-details").classList.remove("hidden");
  },
  showTab: function (tabName) {
    this.expand();

    const toolbar = document.querySelector("#plaintoolbar");
    const tab = toolbar.querySelector(`div[data-toolbar-tab=${tabName}]`);

    // If the tab doesn't exist for some reason, quit
    if (!tab) {
      console.warn(`Toolbar tab ${tabName} does not exist`);
      return;
    }

    // Hide all children in the tab parent
    for (let i = 0; i < tab.parentNode.children.length; i++) {
      const child = tab.parentNode.children[i];
      if (child !== tab) {
        child.classList.add("hidden");
      }
    }

    tab.classList.remove("hidden");

    for (const tab of toolbar.querySelectorAll("button[data-toolbar-tab]")) {
      if (tab.dataset.toolbarTab === tabName) {
        tab.setAttribute("data-active", true);
      } else {
        tab.removeAttribute("data-active");
      }
    }
    localStorage.setItem("plaintoolbar.tab", tabName);
  },
  resetHeight: () => {
    const content = document.querySelector(
      "#plaintoolbar-details > div.overflow-auto",
    );
    if (content) {
      content.style.height = "";
    }
    localStorage.removeItem("plaintoolbar.height");
  },
  setHeight: (height) => {
    const content = document.querySelector(
      "#plaintoolbar-details > div.overflow-auto",
    );
    if (content) {
      content.style.height = height;
    }
  },
};

// Render it hidden immediately if the user has hidden it before
if (window.plainToolbar.shouldHide()) {
  window.plainToolbar.hide();
}

window.addEventListener("load", () => {
  // Restore expanded/collapsed state
  const state = localStorage.getItem("plaintoolbar.expanded");
  if (state === "1") {
    window.plainToolbar.expand();
    // Restore last active tab
    const lastTab = localStorage.getItem("plaintoolbar.tab");
    if (lastTab) {
      window.plainToolbar.showTab(lastTab);
    }
    // Restore custom height if it was set
    const savedHeight = localStorage.getItem("plaintoolbar.height");
    if (savedHeight) {
      window.plainToolbar.setHeight(savedHeight);
    }
  } else if (state === "0") {
    window.plainToolbar.collapse();
  }
  const toolbar = document.querySelector("#plaintoolbar");
  const hasException = toolbar.querySelector('[data-toolbar-tab="Exception"]');

  if (hasException) {
    window.plainToolbar.show();
    if (!window.plainToolbar.expanded) {
      window.plainToolbar.expandTemporary();
    }
  }

  for (const tab of toolbar.querySelectorAll("button[data-toolbar-tab]")) {
    tab.addEventListener("click", () => {
      window.plainToolbar.showTab(tab.dataset.toolbarTab);
    });
  }

  for (const btn of toolbar.querySelectorAll("[data-plaintoolbar-hide]")) {
    btn.addEventListener("click", () => {
      window.plainToolbar.hide();
    });
  }

  for (const btn of toolbar.querySelectorAll("[data-plaintoolbar-hideuntil]")) {
    btn.addEventListener("click", () => {
      console.log("Hiding admin toolbar for 1 hour");
      window.plainToolbar.hideUntil(Date.now() + 3600000);
    });
  }

  for (const btn of toolbar.querySelectorAll("[data-plaintoolbar-expand]")) {
    btn.addEventListener("click", () => {
      window.plainToolbar.toggleExpand();
    });
  }

  // Enable manual resize of the expanded toolbar via drag handle
  const details = document.getElementById("plaintoolbar-details");
  if (details) {
    const handle = details.querySelector("[data-resizer]");
    const content = handle.nextElementSibling;
    let isDragging = false;
    let startY = 0;
    let startHeight = 0;
    let currentHeight = null;
    if (handle && content) {
      // Start dragging
      handle.addEventListener("mousedown", (e) => {
        isDragging = true;
        startY = e.clientY;
        startHeight = content.offsetHeight;
        handle.classList.add("cursor-grabbing");
        handle.classList.remove("cursor-grab");
        // Prevent text selection while dragging
        document.body.classList.add("select-none");
        e.preventDefault();
      });
      // Handle dragging
      document.addEventListener("mousemove", (e) => {
        if (!isDragging) return;
        const delta = e.clientY - startY;
        // Calculate new height: dragging up increases height
        let newHeight = startHeight - delta;
        // Clamp between reasonable bounds
        const minHeight = 50;
        const maxHeight = window.innerHeight - 100;
        newHeight = Math.max(minHeight, Math.min(maxHeight, newHeight));
        currentHeight = `${newHeight}px`;
        window.plainToolbar.setHeight(currentHeight);
      });
      // End dragging
      document.addEventListener("mouseup", () => {
        if (isDragging) {
          isDragging = false;
          handle.classList.add("cursor-grab");
          handle.classList.remove("cursor-grabbing");
          document.body.classList.remove("select-none");
          // Save the new height to localStorage
          if (currentHeight) {
            localStorage.setItem("plaintoolbar.height", currentHeight);
          }
        }
      });
    }
  }
});
