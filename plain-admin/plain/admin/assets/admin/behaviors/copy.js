/*
 * data-copy-value — write the attribute value to the clipboard on
 * click, with a brief "Copied!" confirmation. The text-swap target is
 * a [data-copy-feedback] descendant; falls back to the trigger's
 * lastElementChild if no explicit target is marked.
 *
 *   <button data-copy-value="abc-123">
 *     Copy ID: <span data-copy-feedback>abc-123</span>
 *   </button>
 */
jQuery(($) => {
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
});
