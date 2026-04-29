/*
 * data-column-autolink — turn a table cell into a link to the value's
 * detail page. The cell's content is wrapped in an `<a href>` whose
 * URL is the attribute value. No-op if the cell already contains an
 * `<a>` (so cells with their own explicit links aren't double-wrapped).
 *
 * Re-runs after every HTMX swap so newly-inserted rows pick up the
 * autolink without a page reload.
 */
jQuery(($) => {
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
});
