(() => {
  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const localTz = Intl.DateTimeFormat().resolvedOptions().timeZone;

  function relativeTime(date) {
    const diffSec = Math.round((date - Date.now()) / 1000);
    const diffMin = Math.round(diffSec / 60);
    const diffHr = Math.round(diffMin / 60);
    const diffDay = Math.round(diffHr / 24);
    const diffMonth = Math.round(diffDay / 30);
    const diffYear = Math.round(diffDay / 365);

    if (Math.abs(diffSec) < 60) return rtf.format(diffSec, "second");
    if (Math.abs(diffMin) < 60) return rtf.format(diffMin, "minute");
    if (Math.abs(diffHr) < 24) return rtf.format(diffHr, "hour");
    if (Math.abs(diffDay) < 30) return rtf.format(diffDay, "day");
    if (Math.abs(diffMonth) < 12) return rtf.format(diffMonth, "month");
    return rtf.format(diffYear, "year");
  }

  function formatDatetime(date, timeZone) {
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      second: "2-digit",
      timeZone: timeZone,
    }).format(date);
  }

  function createRow(label, value) {
    const row = document.createElement("div");
    row.className =
      "flex justify-between items-center gap-4 px-2 py-1 cursor-pointer rounded hover:bg-accent hover:text-accent-foreground";
    row.dataset.copyValue = value;

    const labelEl = document.createElement("span");
    labelEl.className = "text-admin-muted-foreground text-xs shrink-0";
    labelEl.textContent = label;

    const valueEl = document.createElement("span");
    valueEl.className = "tabular-nums text-right";
    valueEl.dataset.copyFeedback = "";
    valueEl.textContent = value;

    row.appendChild(labelEl);
    row.appendChild(valueEl);
    return row;
  }

  function wrap(target) {
    target.querySelectorAll("time[datetime]").forEach((timeEl) => {
      // Idempotent: skip if already wrapped (e.g., HTMX swap re-runs).
      if (timeEl.closest(".admin-hovercard")) return;

      const panel = document.createElement("div");
      panel.dataset.hovercard = "";
      panel.setAttribute("aria-hidden", "true");
      panel.className = "min-w-56 flex flex-col";

      const wrapper = document.createElement("span");
      wrapper.className = "admin-hovercard";
      timeEl.parentNode.insertBefore(wrapper, timeEl);
      wrapper.appendChild(timeEl);
      wrapper.appendChild(panel);

      // Build the panel rows on first show — list views can have hundreds
      // of <time> elements, and most are never hovered. Subsequent shows
      // refresh the relative-time row in place.
      let relativeRow;
      wrapper.addEventListener("hovercard:show", () => {
        const date = new Date(timeEl.getAttribute("datetime"));
        if (!relativeRow) {
          panel.appendChild(createRow(localTz, formatDatetime(date, localTz)));
          panel.appendChild(createRow("UTC", formatDatetime(date, "UTC")));
          relativeRow = createRow("Relative", relativeTime(date));
          panel.appendChild(relativeRow);
          panel.appendChild(createRow("Unix", String(Math.floor(date.getTime() / 1000))));
          panel.appendChild(createRow("ISO", timeEl.getAttribute("datetime")));
          return;
        }
        const rel = relativeTime(date);
        relativeRow.dataset.copyValue = rel;
        relativeRow.querySelector("[data-copy-feedback]").textContent = rel;
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => wrap(document));
  document.addEventListener("htmx:afterSwap", (evt) => wrap(evt.detail.target));
})();
