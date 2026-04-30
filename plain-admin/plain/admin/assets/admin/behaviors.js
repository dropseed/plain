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

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-encrypted]");
  if (!el) return;
  if (e.target.closest("code")) return;
  el.dataset.revealed = el.dataset.revealed === "true" ? "false" : "true";
});
