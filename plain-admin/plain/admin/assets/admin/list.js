const SENTINEL_ALL = "__all__";

let actionCheckboxes = [];
let actionCheckboxHeader = null;
let actionIdsInput = null;
let actionForm = null;

function refreshActionCache() {
  actionCheckboxes = [...document.querySelectorAll("[data-action-checkbox]")];
  actionCheckboxHeader = document.querySelector("[data-action-checkbox-all]");
  actionIdsInput = document.querySelector('[name="action_ids"]');
  actionForm = document.querySelector("[data-actions-form]");
}

document.addEventListener("DOMContentLoaded", refreshActionCache);
document.addEventListener("htmx:afterSwap", refreshActionCache);

let lastActionCheckboxChecked = null;

function updateActionIds() {
  if (!actionIdsInput) return;
  if (actionCheckboxHeader?.checked) {
    actionIdsInput.value = SENTINEL_ALL;
  } else {
    const ids = [];
    actionCheckboxes.forEach((cb) => {
      if (cb.checked) ids.push(cb.getAttribute("name"));
    });
    actionIdsInput.value = ids.join(",");
  }
}

document.addEventListener("change", (e) => {
  const target = e.target;
  if (!(target instanceof HTMLInputElement)) return;

  if (target.matches("[data-action-checkbox]")) {
    if (actionCheckboxHeader?.checked) {
      const checkedCount = actionCheckboxes.filter((cb) => cb.checked).length;
      if (checkedCount !== actionCheckboxes.length) actionCheckboxHeader.checked = false;
    }
    updateActionIds();
    return;
  }

  if (target.matches("[data-action-checkbox-all]")) {
    actionCheckboxes.forEach((cb) => {
      cb.checked = target.checked;
    });
    updateActionIds();
  }
});

document.addEventListener("change", (e) => {
  const select = e.target;
  if (!select.matches('[name="action_name"]')) return;
  if (!select.value) return;

  const actionName = select.value;
  const ids = actionIdsInput?.value ?? "";
  const count = ids && ids !== SENTINEL_ALL ? ids.split(",").length : 0;
  const target =
    ids === SENTINEL_ALL
      ? "ALL items across all pages"
      : count > 0
        ? `${count} selected ${count === 1 ? "item" : "items"}`
        : null;
  const confirmMessage = target
    ? `Are you sure you want to perform "${actionName}" on ${target}?`
    : `Are you sure you want to perform "${actionName}"?`;

  if (confirm(confirmMessage)) {
    actionForm?.submit();
  } else {
    select.value = "";
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
    updateActionIds();
  } else {
    lastActionCheckboxChecked = target;
  }
});

// Merge query params with the current url and the link url.
document.querySelectorAll("[data-merge-params]").forEach((link) => {
  const currentUrl = new URL(window.location.href);
  const params = new URL(link.getAttribute("href"), window.location.href).searchParams;
  params.forEach((value, key) => {
    currentUrl.searchParams.set(key, value);
  });
  link.setAttribute("href", currentUrl.toString());
});
