/**
 * Admin menu — filter input inside the menu popover, plus drag-and-drop
 * reordering for pinned tabs in the header strip. The popover's
 * open/close behavior comes from basecoat (assets/admin/components/popover.js)
 * — this file only wires the filter and the tab DnD.
 */
document.addEventListener("DOMContentLoaded", () => {
  const filterInput = document.getElementById("menu-filter-input");
  const menuPopover = document.getElementById("admin-menu-popover");

  if (filterInput) {
    filterInput.addEventListener("input", (e) => {
      filterItems(e.target.value.toLowerCase());
    });
  }

  // Reset and focus the filter every time the menu popover opens.
  // plain-admin:popover-open fires from components.js when a popover starts
  // opening (before aria-hidden is flipped, so defer the focus by a frame).
  if (filterInput && menuPopover) {
    document.addEventListener("plain-admin:popover-open", (e) => {
      if (!e.detail.source.contains(menuPopover)) return;
      setTimeout(() => {
        filterInput.value = "";
        filterItems("");
        filterInput.focus();
      }, 0);
    });
  }

  function filterItems(query) {
    const container = document.getElementById("menu-items-container");
    if (!container) return;
    const sections = container.querySelectorAll(".menu-section");
    const subsections = container.querySelectorAll(".menu-subsection");
    const itemGroups = container.querySelectorAll(".menu-items-group");

    // Find sub-sections whose name matches the query — items in those
    // groups all show even if their own title doesn't match.
    const matchingSections = new Set();
    subsections.forEach((subsection) => {
      const sectionName = subsection.getAttribute("data-section") || "";
      if (query !== "" && sectionName.includes(query)) {
        matchingSections.add(sectionName);
      }
    });

    // Show items by title match OR by being in a matching sub-section.
    itemGroups.forEach((group) => {
      const groupSection = group.getAttribute("data-section") || "";
      const sectionMatches = matchingSections.has(groupSection);
      group.querySelectorAll(".menu-item").forEach((item) => {
        const title = item.getAttribute("data-title") || "";
        const titleMatches = query === "" || title.includes(query);
        item.style.display = titleMatches || sectionMatches ? "" : "none";
      });
    });

    // Hide sub-section headers with no visible items left.
    subsections.forEach((subsection) => {
      const nextGroup = subsection.nextElementSibling;
      if (nextGroup?.classList.contains("menu-items-group")) {
        const hasVisibleItems = Array.from(nextGroup.querySelectorAll(".menu-item")).some(
          (item) => item.style.display !== "none",
        );
        subsection.style.display = hasVisibleItems ? "" : "none";
      }
    });

    // Hide the App / Packages section entirely if nothing under it
    // matches.
    sections.forEach((section) => {
      const visibleItems = Array.from(section.querySelectorAll(".menu-item")).filter(
        (item) => item.style.display !== "none",
      );
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
    document.querySelectorAll(".nav-tab").forEach((el) => {
      el.classList.remove("drag-over");
    });
  });

  document.addEventListener("dragover", (e) => {
    const tab = e.target.closest(".nav-tab[data-slug]");
    if (!tab || tab === draggedTab) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    document.querySelectorAll(".nav-tab").forEach((el) => {
      el.classList.remove("drag-over");
    });
    tab.classList.add("drag-over");
  });

  document.addEventListener("drop", (e) => {
    const targetTab = e.target.closest(".nav-tab[data-slug]");
    if (!targetTab || !draggedTab || targetTab === draggedTab) return;
    e.preventDefault();
    targetTab.before(draggedTab);
    targetTab.classList.remove("drag-over");

    const container = document.getElementById("nav-tabs-container");
    const newOrder = Array.from(container.querySelectorAll(".nav-tab[data-slug]")).map(
      (t) => t.dataset.slug,
    );
    const reorderUrl = container.dataset.reorderUrl;
    if (reorderUrl) {
      fetch(reorderUrl, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: `slugs=${encodeURIComponent(JSON.stringify(newOrder))}`,
      });
    }
  });
});
