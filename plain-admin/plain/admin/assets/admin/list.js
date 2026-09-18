const SENTINEL_ALL = "__all__";

let actionCheckboxes = [];
let actionCheckboxHeader = null;
let actionIdsInput = null;
let actionNameInput = null;
let actionForm = null;
let selectionHeader = null;
let selectionSummary = null;
let selectAllButton = null;
let actionMenuItems = [];

// All-pages selection is an explicit mode, entered only via the "Select all N"
// button. Any deselection exits it. When active, action_ids is the __all__
// sentinel the backend expands to every object across every page.
let selectAllPages = false;
let lastActionCheckboxChecked = null;

function refreshActionCache() {
  actionCheckboxes = [...document.querySelectorAll("[data-action-checkbox]")];
  actionCheckboxHeader = document.querySelector("[data-action-checkbox-all]");
  actionForm = document.querySelector("[data-actions-form]");
  actionIdsInput = actionForm?.querySelector('[name="action_ids"]') ?? null;
  actionNameInput = actionForm?.querySelector('[name="action_name"]') ?? null;
  selectionHeader = actionForm?.closest("header") ?? null;
  selectionSummary = document.querySelector("[data-selection-summary]");
  selectAllButton = document.querySelector("[data-action-select-all]");
  actionMenuItems = [...document.querySelectorAll("[data-action-name]")];
  updateSelectionUI();
}

document.addEventListener("DOMContentLoaded", refreshActionCache);
document.addEventListener("htmx:afterSwap", () => {
  selectAllPages = false;
  lastActionCheckboxChecked = null;
  refreshActionCache();
});

function checkedCount() {
  return actionCheckboxes.filter((cb) => cb.checked).length;
}

function totalCount() {
  return parseInt(actionForm?.dataset.totalCount ?? "0", 10);
}

function updateSelectionUI() {
  const totalOnPage = actionCheckboxes.length;
  const checked = checkedCount();
  const total = totalCount();
  const fullPageSelected = totalOnPage > 0 && checked === totalOnPage;

  // Header checkbox reflects the current page: checked when the whole page is
  // selected, indeterminate when only some rows are.
  if (actionCheckboxHeader) {
    actionCheckboxHeader.checked = fullPageSelected;
    actionCheckboxHeader.indeterminate = checked > 0 && checked < totalOnPage;
  }

  // Presence-based flag that swaps the results count for the selection bar.
  if (selectionHeader) {
    if (checked > 0) selectionHeader.setAttribute("data-selecting", "");
    else selectionHeader.removeAttribute("data-selecting");
  }

  if (selectionSummary) {
    selectionSummary.textContent = selectAllPages ? `All ${total} selected` : `${checked} selected`;
  }

  // The Actions dropdown is always visible, but its items only act when
  // something is selected — disable them otherwise (CSS dims + blocks them,
  // components.js drops them from keyboard nav, and the menu heading hints why).
  actionMenuItems.forEach((item) => {
    if (checked > 0) item.removeAttribute("aria-disabled");
    else item.setAttribute("aria-disabled", "true");
  });

  // Offer "Select all N" only once the whole page is selected, we're not
  // already in all-pages mode, and there's more than this page to select.
  if (selectAllButton) {
    const showSelectAll = fullPageSelected && !selectAllPages && total > totalOnPage;
    selectAllButton.classList.toggle("hidden", !showSelectAll);
  }

  if (actionIdsInput) {
    if (selectAllPages) {
      actionIdsInput.value = SENTINEL_ALL;
    } else {
      const ids = actionCheckboxes.filter((cb) => cb.checked).map((cb) => cb.getAttribute("name"));
      actionIdsInput.value = ids.join(",");
    }
  }
}

document.addEventListener("change", (e) => {
  const target = e.target;
  if (!(target instanceof HTMLInputElement)) return;

  if (target.matches("[data-action-checkbox]")) {
    if (!target.checked) selectAllPages = false;
    updateSelectionUI();
    return;
  }

  if (target.matches("[data-action-checkbox-all]")) {
    actionCheckboxes.forEach((cb) => {
      cb.checked = target.checked;
    });
    if (!target.checked) selectAllPages = false;
    updateSelectionUI();
  }
});

document.addEventListener("click", (e) => {
  const target = e.target;
  if (!(target instanceof Element)) return;

  if (target.closest("[data-action-select-all]")) {
    selectAllPages = true;
    updateSelectionUI();
    return;
  }

  if (target.closest("[data-action-clear]")) {
    actionCheckboxes.forEach((cb) => {
      cb.checked = false;
    });
    selectAllPages = false;
    updateSelectionUI();
    return;
  }

  const actionItem = target.closest("[data-action-name]");
  if (actionItem) {
    if (actionItem.getAttribute("aria-disabled") === "true") return;
    const actionName = actionItem.getAttribute("data-action-name");
    const checked = checkedCount();
    const confirmMessage = selectAllPages
      ? `Are you sure you want to perform "${actionName}" on all ${totalCount()} items across all pages?`
      : `Are you sure you want to perform "${actionName}" on ${checked} selected item${checked === 1 ? "" : "s"}?`;

    if (confirm(confirmMessage)) {
      if (actionNameInput) actionNameInput.value = actionName;
      actionForm?.submit();
    }
    // The dropdown-menu component closes itself on menuitem click, so a
    // cancelled confirm just leaves the menu closed with the selection intact.
  }
});

// Shift-click to select a range of action checkboxes.
document.addEventListener("click", (e) => {
  const target = e.target;
  if (!(target instanceof HTMLInputElement)) return;
  if (!target.matches("[data-action-checkbox]")) return;

  if (e.shiftKey && lastActionCheckboxChecked) {
    const thisIndex = actionCheckboxes.indexOf(target);
    const lastIndex = actionCheckboxes.indexOf(lastActionCheckboxChecked);
    if (thisIndex === -1 || lastIndex === -1) return;
    const min = Math.min(thisIndex, lastIndex);
    const max = Math.max(thisIndex, lastIndex);
    for (let i = min; i <= max; i++) actionCheckboxes[i].checked = target.checked;
    if (!target.checked) selectAllPages = false;
    updateSelectionUI();
  } else {
    lastActionCheckboxChecked = target;
  }
});

// Merge query params with the current url and the link url.
document.querySelectorAll("[data-merge-params]").forEach((link) => {
  const currentUrl = new URL(window.location.href);
  const params = new URL(link.getAttribute("href"), window.location.href).searchParams;
  params.forEach((value, key) => {
    // An empty value means "remove this param" (e.g. clearing the sort).
    if (value === "") {
      currentUrl.searchParams.delete(key);
    } else {
      currentUrl.searchParams.set(key, value);
    }
  });
  link.setAttribute("href", currentUrl.toString());
});
