function autolinkColumns(target) {
  const root = target instanceof Element || target instanceof Document ? target : document;
  root.querySelectorAll("[data-column-autolink]").forEach((cell) => {
    if (cell.querySelector("a")) return;
    const url = cell.dataset.columnAutolink;
    if (!url) return;
    const link = document.createElement("a");
    link.href = url;
    link.className = "flex p-2 -m-2 text-admin-foreground hover:no-underline";
    while (cell.firstChild) link.appendChild(cell.firstChild);
    cell.appendChild(link);
  });
}

autolinkColumns(document);
document.addEventListener("htmx:afterSwap", (evt) => autolinkColumns(evt.detail.target));

function submitFormClean(form) {
  const target = new URL(
    form.getAttribute("action") || window.location.pathname,
    window.location.href,
  );
  // A form that stays on the current view (filter, search, pagination) merges its
  // fields onto the current query string so unrelated params like the active sort
  // survive; a form that navigates elsewhere (e.g. global search) starts clean.
  const sameView = target.pathname === window.location.pathname;
  if (sameView) {
    target.search = window.location.search;
  }
  const data = new FormData(form);
  for (const [key, value] of data.entries()) {
    if (value) {
      target.searchParams.set(key, value);
    } else {
      target.searchParams.delete(key);
    }
  }
  // Any same-view control other than pagination returns to the first page.
  if (sameView && !data.has("page")) {
    target.searchParams.delete("page");
  }
  window.location.href = target.toString();
}

document.addEventListener("change", (e) => {
  const target = e.target.closest("[data-autosubmit]");
  if (!target) return;
  submitFormClean(target.closest("form"));
});

document.addEventListener("submit", (e) => {
  const form = e.target;
  if (!(form instanceof HTMLFormElement)) return;
  if (form.method.toLowerCase() !== "get") return;
  e.preventDefault();
  submitFormClean(form);
});

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-copy-value]");
  if (!el) return;
  // Copy rows can sit inside an autolinked cell (the whole cell wrapped in an
  // <a>), e.g. the datetime hovercard. A copy click means "copy", not
  // "follow the row link" — stop the anchor from navigating.
  e.preventDefault();
  const value = el.dataset.copyValue;
  const feedback = el.querySelector("[data-copy-feedback]") || el.lastElementChild;
  if (!feedback) return;
  navigator.clipboard.writeText(value).then(() => {
    const original = feedback.textContent;
    feedback.textContent = "Copied!";
    setTimeout(() => {
      feedback.textContent = original;
    }, 1000);
  });
});

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-encrypted]");
  if (!el) return;
  if (e.target.closest("code")) return;
  el.dataset.revealed = el.dataset.revealed === "true" ? "false" : "true";
});
