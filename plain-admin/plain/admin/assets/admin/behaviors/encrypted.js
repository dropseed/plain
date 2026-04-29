/*
 * data-encrypted — toggle reveal of an encrypted value (used by the
 * admin's display for things like API keys). Click to reveal; click
 * again to hide. Clicking inside the revealed <code> is ignored so
 * the user can select text to copy without re-toggling.
 */
jQuery(($) => {
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
