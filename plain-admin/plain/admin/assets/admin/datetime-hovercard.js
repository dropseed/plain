/*
 * Wraps every <time datetime="..."> in a .hovercard with a panel of
 * label/value rows (local timezone, UTC, relative, Unix, ISO). Each row
 * carries data-copy-value so the generic click-to-copy handler in
 * admin.js writes its value to the clipboard on click.
 *
 * Show/hide and positioning live in components/hovercard.js — this
 * file is just the row constructor.
 */
jQuery(($) => {
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
    labelEl.className = "text-muted-foreground text-xs shrink-0";
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
    $(target)
      .find("time[datetime]")
      .each(function () {
        // Idempotent: skip if already wrapped (e.g., HTMX swap re-runs).
        if (this.closest(".hovercard")) return;

        const date = new Date(this.getAttribute("datetime"));
        const unix = Math.floor(date.getTime() / 1000);

        const panel = document.createElement("div");
        panel.dataset.hovercard = "";
        panel.setAttribute("aria-hidden", "true");
        panel.className = "min-w-56 flex flex-col";

        panel.appendChild(createRow(localTz, formatDatetime(date, localTz)));
        panel.appendChild(createRow("UTC", formatDatetime(date, "UTC")));
        const relativeRow = createRow("Relative", relativeTime(date));
        panel.appendChild(relativeRow);
        panel.appendChild(createRow("Unix", String(unix)));
        panel.appendChild(createRow("ISO", this.getAttribute("datetime")));

        const wrapper = document.createElement("span");
        wrapper.className = "hovercard";
        this.parentNode.insertBefore(wrapper, this);
        wrapper.appendChild(this);
        wrapper.appendChild(panel);

        // Refresh the relative time on each show — "5 minutes ago" goes
        // stale if the user leaves the tab open. hovercard.js fires this
        // event before applying the show transition.
        wrapper.addEventListener("hovercard:show", () => {
          const rel = relativeTime(date);
          relativeRow.dataset.copyValue = rel;
          relativeRow.querySelector("[data-copy-feedback]").textContent = rel;
        });
      });
  }

  wrap(document);
  htmx.on("htmx:afterSwap", (evt) => wrap(evt.detail.target));
});
