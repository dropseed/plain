// Make this available to the JS console for the user
const plainToolbar = {
  hide: function () {
    // Hide by inserting a style so it doesn't flash on page load
    const style = document.createElement("style");
    style.innerHTML = "#plaintoolbar { display: none; }";
    document.getElementsByTagName("head")[0].appendChild(style);
    this.stylesheet = style;
  },
  show: function () {
    localStorage.removeItem("plaintoolbar.hidden_until");
    if (this.stylesheet) {
      this.stylesheet.remove();
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
        child.style.display = "none";
      }
    }

    tab.style.display = "block";

    for (const tab of toolbar.querySelectorAll("button[data-toolbar-tab]")) {
      if (tab.dataset.toolbarTab === tabName) {
        tab.setAttribute("data-active", true);
      } else {
        tab.removeAttribute("data-active");
      }
    }
    localStorage.setItem("plaintoolbar.tab", tabName);
  },
};

// Render it hidden immediately if the user has hidden it before
if (plainToolbar.shouldHide()) {
  plainToolbar.hide();
}

window.addEventListener("load", () => {
  // Restore expanded/collapsed state
  const state = localStorage.getItem("plaintoolbar.expanded");
  if (state === "1") {
    plainToolbar.expand();
    // Restore last active tab
    const lastTab = localStorage.getItem("plaintoolbar.tab");
    if (lastTab) {
      plainToolbar.showTab(lastTab);
    }
  } else if (state === "0") {
    plainToolbar.collapse();
  }
  const toolbar = document.querySelector("#plaintoolbar");

  for (const tab of toolbar.querySelectorAll("button[data-toolbar-tab]")) {
    tab.addEventListener("click", () => {
      plainToolbar.showTab(tab.dataset.toolbarTab);
    });
  }

  for (const btn of toolbar.querySelectorAll("[data-plaintoolbar-hide]")) {
    btn.addEventListener("click", () => {
      plainToolbar.hide();
    });
  }

  for (const btn of toolbar.querySelectorAll("[data-plaintoolbar-hideuntil]")) {
    btn.addEventListener("click", () => {
      console.log("Hiding admin toolbar for 1 hour");
      plainToolbar.hideUntil(Date.now() + 3600000);
    });
  }

  for (const btn of toolbar.querySelectorAll("[data-plaintoolbar-expand]")) {
    btn.addEventListener("click", () => {
      plainToolbar.toggleExpand();
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
    if (handle && content) {
      // Initial cursor
      handle.style.cursor = "grab";
      // Start dragging
      handle.addEventListener("mousedown", (e) => {
        isDragging = true;
        startY = e.clientY;
        startHeight = content.offsetHeight;
        handle.style.cursor = "grabbing";
        // Prevent text selection while dragging
        document.body.style.userSelect = "none";
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
        content.style.height = `${newHeight}px`;
      });
      // End dragging
      document.addEventListener("mouseup", () => {
        if (isDragging) {
          isDragging = false;
          handle.style.cursor = "grab";
          document.body.style.userSelect = "";
        }
      });
    }
  }
});
