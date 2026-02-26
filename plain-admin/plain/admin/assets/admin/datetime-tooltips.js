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

  function createTooltipRow(label, value) {
    const row = document.createElement("div");
    row.className =
      "flex justify-between items-center gap-4 px-2 py-1 cursor-pointer rounded hover:bg-stone-100";
    row.dataset.copyValue = value;

    const labelEl = document.createElement("span");
    labelEl.className = "text-black/50 text-xs shrink-0";
    labelEl.textContent = label;

    const valueEl = document.createElement("span");
    valueEl.className = "tabular-nums text-right";
    valueEl.textContent = value;

    row.appendChild(labelEl);
    row.appendChild(valueEl);
    return row;
  }

  function createDatetimeTooltips(target) {
    $(target)
      .find("time[datetime]")
      .each(function () {
        if (this._datetimeTooltip) return;

        const date = new Date(this.getAttribute("datetime"));
        const unix = Math.floor(date.getTime() / 1000);

        const tooltip = document.createElement("div");
        tooltip.className =
          "hidden flex-col fixed z-50 bg-white text-black/90 border border-stone-200 shadow-lg rounded-md p-1 text-sm min-w-56 whitespace-nowrap";

        tooltip.appendChild(createTooltipRow(localTz, formatDatetime(date, localTz)));
        tooltip.appendChild(createTooltipRow("UTC", formatDatetime(date, "UTC")));
        const relativeRow = createTooltipRow("Relative", relativeTime(date));
        tooltip.appendChild(relativeRow);
        tooltip.appendChild(createTooltipRow("Unix", String(unix)));
        tooltip.appendChild(createTooltipRow("ISO", this.getAttribute("datetime")));

        document.body.appendChild(tooltip);
        this._datetimeTooltip = tooltip;

        let hideTimeout;
        const show = () => {
          clearTimeout(hideTimeout);
          const rel = relativeTime(date);
          relativeRow.dataset.copyValue = rel;
          relativeRow.lastElementChild.textContent = rel;
          const rect = this.getBoundingClientRect();
          tooltip.style.top = `${rect.bottom + 4}px`;
          tooltip.style.left = `${rect.left}px`;
          tooltip.classList.replace("hidden", "flex");
        };
        const hide = () => {
          hideTimeout = setTimeout(() => tooltip.classList.replace("flex", "hidden"), 100);
        };

        this.addEventListener("mouseenter", show);
        this.addEventListener("mouseleave", hide);
        tooltip.addEventListener("mouseenter", show);
        tooltip.addEventListener("mouseleave", hide);
      });
  }

  $(document).on("click", "[data-copy-value]", function () {
    const value = this.dataset.copyValue;
    const valueEl = this.lastElementChild;
    navigator.clipboard.writeText(value).then(() => {
      const original = valueEl.textContent;
      valueEl.textContent = "Copied!";
      setTimeout(() => {
        valueEl.textContent = original;
      }, 1000);
    });
  });

  createDatetimeTooltips(document);

  htmx.on("htmx:afterSwap", (evt) => {
    createDatetimeTooltips(evt.detail.target);
  });
});
