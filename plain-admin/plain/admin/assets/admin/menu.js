/**
 * Admin Menu - handles menu dialog, filter, and nav tab drag-and-drop
 */
document.addEventListener("DOMContentLoaded", () => {
  const dialog = document.getElementById("admin-menu-dialog");
  const filterInput = document.getElementById("menu-filter-input");

  function openMenu() {
    dialog.showModal();
    filterInput.value = "";
    filterInput.focus();
    filterItems("");
  }

  function closeMenu() {
    dialog.close();
  }

  // Menu toggle buttons (use class for both mobile and desktop)
  document.addEventListener("click", (e) => {
    if (e.target.closest(".menu-toggle")) {
      if (dialog.open) {
        closeMenu();
      } else {
        openMenu();
      }
    }
  });

  // Close on backdrop click (click on dialog itself, not its contents)
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog) {
      closeMenu();
    }
  });

  // Filter functionality
  filterInput.addEventListener("input", (e) => {
    filterItems(e.target.value.toLowerCase());
  });

  function filterItems(query) {
    const container = document.getElementById("menu-items-container");
    const sections = container.querySelectorAll(".menu-section");
    const subsections = container.querySelectorAll(".menu-subsection");
    const itemGroups = container.querySelectorAll(".menu-items-group");

    // First, find which sections match the query
    const matchingSections = new Set();
    subsections.forEach((subsection) => {
      const sectionName = subsection.getAttribute("data-section") || "";
      if (query !== "" && sectionName.includes(query)) {
        matchingSections.add(sectionName);
      }
    });

    // Show/hide items based on title match OR being in a matching section
    itemGroups.forEach((group) => {
      const groupSection = group.getAttribute("data-section") || "";
      const sectionMatches = matchingSections.has(groupSection);

      group.querySelectorAll(".menu-item").forEach((item) => {
        const title = item.getAttribute("data-title") || "";
        const titleMatches = query === "" || title.includes(query);
        item.style.display = titleMatches || sectionMatches ? "" : "none";
      });
    });

    // Show/hide subsection headers
    subsections.forEach((subsection) => {
      const nextGroup = subsection.nextElementSibling;
      if (nextGroup?.classList.contains("menu-items-group")) {
        const hasVisibleItems = Array.from(
          nextGroup.querySelectorAll(".menu-item"),
        ).some((item) => item.style.display !== "none");
        subsection.style.display = hasVisibleItems ? "" : "none";
      }
    });

    // Hide empty top-level sections (App/Packages)
    sections.forEach((section) => {
      const visibleItems = Array.from(
        section.querySelectorAll(".menu-item"),
      ).filter((item) => item.style.display !== "none");
      section.style.display = visibleItems.length > 0 ? "" : "none";
    });
  }

  // Drag and drop for nav bar tabs (pinned items only)
  let draggedTab = null;

  document.addEventListener("dragstart", (e) => {
    const tab = e.target.closest(".nav-tab[data-slug]");
    if (!tab) return;
    draggedTab = tab;
    tab.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", tab.dataset.slug);
  });

  document.addEventListener("dragend", (e) => {
    const tab = e.target.closest(".nav-tab[data-slug]");
    if (!tab) return;
    tab.classList.remove("dragging");
    draggedTab = null;
    // Remove any lingering drag-over styles
    document.querySelectorAll(".nav-tab").forEach((el) => {
      el.classList.remove("drag-over");
    });
  });

  document.addEventListener("dragover", (e) => {
    const tab = e.target.closest(".nav-tab[data-slug]");
    if (!tab || tab === draggedTab) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";

    // Visual feedback - show drop indicator on left side
    document.querySelectorAll(".nav-tab").forEach((el) => {
      el.classList.remove("drag-over");
    });
    tab.classList.add("drag-over");
  });

  document.addEventListener("drop", (e) => {
    const targetTab = e.target.closest(".nav-tab[data-slug]");
    if (!targetTab || !draggedTab || targetTab === draggedTab) return;
    e.preventDefault();

    // Always insert before target (matches the left border indicator)
    targetTab.before(draggedTab);

    // Remove visual feedback
    targetTab.classList.remove("drag-over");

    // Get new order of pinned items and POST to server
    const container = document.getElementById("nav-tabs-container");
    const newOrder = Array.from(
      container.querySelectorAll(".nav-tab[data-slug]"),
    ).map((t) => t.dataset.slug);

    // Get the reorder URL from the container's data attribute
    const reorderUrl = container.dataset.reorderUrl;
    if (reorderUrl) {
      fetch(reorderUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: `slugs=${encodeURIComponent(JSON.stringify(newOrder))}`,
      });
    }
  });
});
