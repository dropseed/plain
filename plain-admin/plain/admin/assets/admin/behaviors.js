/*
 * Plain admin — declarative data-* behaviors.
 *
 * Each section registers a delegated handler on `document` keyed off a
 * `data-*` attribute. Stateless, no per-element initialization, so HTMX
 * swaps need no special handling — except autolink, which mutates the
 * DOM and re-runs after htmx:afterSwap.
 */

// ---------- data-column-autolink ----------
// Wrap a table cell's content in an <a href> link. Skips cells that
// already contain an <a> so explicit links aren't double-wrapped.
function autolinkColumns(target) {
  const root = target instanceof Element || target instanceof Document ? target : document;
  root.querySelectorAll("[data-column-autolink]").forEach((cell) => {
    if (cell.querySelector("a")) return;
    const url = cell.dataset.columnAutolink;
    if (!url) return;
    const link = document.createElement("a");
    link.href = url;
    link.className = "flex p-2 -m-2 text-foreground hover:no-underline";
    while (cell.firstChild) link.appendChild(cell.firstChild);
    cell.appendChild(link);
  });
}

autolinkColumns(document);
htmx.on("htmx:afterSwap", (evt) => autolinkColumns(evt.detail.target));

// ---------- data-autosubmit + GET-form param cleanup ----------
// Submit the enclosing form on `change`. Also intercepts every
// <form method="GET"> submission to strip empty params from the URL —
// keeps list views from accumulating `?q=&filter=` cruft.
function submitFormClean(form) {
  const formData = new FormData(form);
  const params = new URLSearchParams();
  for (const [key, value] of formData.entries()) {
    if (value) {
      params.append(key, value);
    }
  }
  const basePath = form.getAttribute("action") || window.location.pathname;
  const url = params.toString() ? `${basePath}?${params.toString()}` : basePath;
  window.location.href = url;
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

// ---------- data-copy-value ----------
// Click writes the attribute value to the clipboard with a brief
// "Copied!" confirmation. Text-swap target is a [data-copy-feedback]
// descendant; falls back to lastElementChild.
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-copy-value]");
  if (!el) return;
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

// ---------- data-encrypted ----------
// Toggle reveal of an encrypted value (API keys, etc.). Clicks on the
// revealed <code> are ignored so the user can select text without
// re-toggling.
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-encrypted]");
  if (!el) return;
  if (e.target.closest("code")) return;
  const revealed = el.dataset.revealed === "true";
  if (revealed) {
    el.dataset.revealed = "false";
    el.innerHTML = '<i class="bi bi-lock text-xs"></i> ••••••';
    el.classList.add("text-muted-foreground/80", "hover:text-muted-foreground");
    el.classList.remove("text-warning");
  } else {
    const code = document.createElement("code");
    code.className = "text-sm break-all bg-warning/10 rounded px-1 py-0.5 select-all";
    code.textContent = String(el.dataset.encrypted);
    el.dataset.revealed = "true";
    el.replaceChildren();
    const icon = document.createElement("i");
    icon.className = "bi bi-unlock text-xs";
    el.append(icon, " ", code);
    el.classList.remove("text-muted-foreground/80", "hover:text-muted-foreground");
    el.classList.add("text-warning");
  }
});
