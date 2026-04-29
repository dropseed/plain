/*
 * Plain admin — declarative data-* behaviors.
 *
 * Each section registers a delegated handler on `document` keyed off a
 * `data-*` attribute. Stateless, no per-element initialization, so HTMX
 * swaps need no special handling — except autolink, which mutates the
 * DOM and re-runs after htmx:afterSwap.
 */
jQuery(($) => {
  // ---------- data-column-autolink ----------
  // Wrap a table cell's content in an <a href> link. Skips cells that
  // already contain an <a> so explicit links aren't double-wrapped.
  function autolinkColumns(target) {
    $(target)
      .find("[data-column-autolink]")
      .each(function () {
        const $this = $(this);
        if ($this.find("a").length > 0) return;
        const autolinkUrl = $this.data("column-autolink");
        if (!autolinkUrl) return;
        const $link = $(document.createElement("a"));
        $link.attr("href", autolinkUrl);
        $link.addClass("flex p-2 -m-2 text-foreground hover:no-underline");
        $(this).wrapInner($link);
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

  $(document).on("change", "[data-autosubmit]", function () {
    submitFormClean($(this).closest("form")[0]);
  });

  $(document).on("submit", "form[method='GET']", function (e) {
    e.preventDefault();
    submitFormClean(this);
  });

  // ---------- data-copy-value ----------
  // Click writes the attribute value to the clipboard with a brief
  // "Copied!" confirmation. Text-swap target is a [data-copy-feedback]
  // descendant; falls back to lastElementChild.
  $(document).on("click", "[data-copy-value]", function () {
    const value = this.dataset.copyValue;
    const feedback = this.querySelector("[data-copy-feedback]") || this.lastElementChild;
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
  $(document).on("click", "[data-encrypted]", function (e) {
    if ($(e.target).is("code")) return;
    const $el = $(this);
    if ($el.data("revealed")) {
      $el
        .data("revealed", false)
        .html('<i class="bi bi-lock text-xs"></i> ••••••')
        .addClass("text-stone-400 hover:text-stone-500")
        .removeClass("text-amber-900");
    } else {
      const escaped = $("<span>")
        .text(String($el.data("encrypted")))
        .html();
      $el
        .data("revealed", true)
        .html(
          '<i class="bi bi-unlock text-xs"></i> <code class="text-sm break-all bg-amber-50/75 rounded px-1 py-0.5 select-all">' +
            escaped +
            "</code>",
        )
        .removeClass("text-stone-400 hover:text-stone-500")
        .addClass("text-amber-900");
    }
  });
});
