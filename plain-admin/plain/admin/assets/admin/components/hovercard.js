/*
 * Hovercard — hover-triggered version of popover. Plain admin extension
 * to the Basecoat component family (Basecoat itself ships popover but
 * not hovercard). Registers with the Basecoat MutationObserver registry
 * so HTMX-swapped content auto-inits.
 *
 * Markup:
 *   <span class="hovercard">
 *     <some-trigger>...</some-trigger>
 *     <div data-hovercard aria-hidden="true">...panel content...</div>
 *   </span>
 *
 * The first non-[data-hovercard] child is the trigger. mouseenter shows
 * the panel positioned fixed below the trigger; mouseleave hides after
 * a 100ms grace timeout (so the user can move the cursor into the panel
 * to interact with its content).
 */
(() => {
  const initHovercard = (hovercard) => {
    const panel = hovercard.querySelector(":scope > [data-hovercard]");
    const trigger = Array.from(hovercard.children).find((c) => c !== panel);

    if (!trigger || !panel) {
      const missing = [];
      if (!trigger) missing.push("trigger");
      if (!panel) missing.push("[data-hovercard]");
      console.error(
        `Hovercard initialisation failed. Missing element(s): ${missing.join(", ")}`,
        hovercard,
      );
      return;
    }

    let hideTimeout;
    const show = () => {
      clearTimeout(hideTimeout);
      hovercard.dispatchEvent(new CustomEvent("hovercard:show"));
      const rect = trigger.getBoundingClientRect();
      panel.style.top = `${rect.bottom + 4}px`;
      panel.style.left = `${rect.left}px`;
      panel.setAttribute("aria-hidden", "false");
    };
    const hide = () => {
      hideTimeout = setTimeout(() => {
        panel.setAttribute("aria-hidden", "true");
      }, 100);
    };

    trigger.addEventListener("mouseenter", show);
    trigger.addEventListener("mouseleave", hide);
    panel.addEventListener("mouseenter", show);
    panel.addEventListener("mouseleave", hide);

    hovercard.dataset.hovercardInitialized = true;
  };

  if (window.basecoat) {
    window.basecoat.register(
      "hovercard",
      ".hovercard:not([data-hovercard-initialized])",
      initHovercard,
    );
  }
})();
