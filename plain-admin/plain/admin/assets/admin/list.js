const SENTINEL_ALL = "__all__";

const actionCheckboxes = () => document.querySelectorAll("[data-action-checkbox]");
const actionCheckboxHeader = () => document.querySelector("[data-action-checkbox-all]");
const actionIdsInput = () => document.querySelector('[name="action_ids"]');
const actionForm = () => document.querySelector("[data-actions-form]");

let lastActionCheckboxChecked = null;

function updateActionIds() {
  const header = actionCheckboxHeader();
  const idsInput = actionIdsInput();
  if (!idsInput) return;
  if (header?.checked) {
    idsInput.value = SENTINEL_ALL;
  } else {
    const ids = [];
    actionCheckboxes().forEach((cb) => {
      if (cb.checked) ids.push(cb.getAttribute("name"));
    });
    idsInput.value = ids.join(",");
  }
}

document.addEventListener("change", (e) => {
  const target = e.target;
  if (!(target instanceof HTMLInputElement)) return;

  if (target.matches("[data-action-checkbox]")) {
    const header = actionCheckboxHeader();
    if (header?.checked) {
      const all = actionCheckboxes();
      const checkedCount = [...all].filter((cb) => cb.checked).length;
      if (checkedCount !== all.length) header.checked = false;
    }
    updateActionIds();
    return;
  }

  if (target.matches("[data-action-checkbox-all]")) {
    actionCheckboxes().forEach((cb) => {
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
  const idsInput = actionIdsInput();
  const ids = idsInput?.value ?? "";
  let confirmMessage;

  if (ids === SENTINEL_ALL) {
    confirmMessage = `Are you sure you want to perform "${actionName}" on ALL items across all pages?`;
  } else if (ids) {
    const selectedCount = ids.split(",").length;
    const itemText = selectedCount === 1 ? "item" : "items";
    confirmMessage = `Are you sure you want to perform "${actionName}" on ${selectedCount} selected ${itemText}?`;
  } else {
    confirmMessage = `Are you sure you want to perform "${actionName}"?`;
  }

  if (confirm(confirmMessage)) {
    actionForm()?.submit();
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
    const all = [...actionCheckboxes()];
    const thisIndex = all.indexOf(target);
    const lastIndex = all.indexOf(lastActionCheckboxChecked);
    if (thisIndex === -1 || lastIndex === -1) return;
    const min = Math.min(thisIndex, lastIndex);
    const max = Math.max(thisIndex, lastIndex);
    for (let i = min; i <= max; i++) all[i].checked = target.checked;
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
