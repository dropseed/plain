/*
 * Plain admin theme toggle.
 *
 * Choice ("light" | "dark" | "system") stored in localStorage under
 * "plain-admin-theme"; <html> gets a `dark` class when resolved dark.
 * No-flash init runs as an inline script in <head> (see base.html);
 * this file wires the toggle buttons and OS-preference listener.
 *
 * The buttons live inside a `.segmented` (see components.js), which
 * handles roving tabindex and arrow-key navigation off `aria-checked`.
 */
(() => {
  const STORAGE_KEY = "plain-admin-theme";
  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  const getChoice = () => {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === "light" || v === "dark" ? v : "system";
  };

  const apply = (choice) => {
    const dark = choice === "dark" || (choice === "system" && media.matches);
    root.classList.toggle("dark", dark);
  };

  const refreshButtons = () => {
    const choice = getChoice();
    document.querySelectorAll("[data-theme-set]").forEach((item) => {
      const expected = item.dataset.themeSet === choice ? "true" : "false";
      if (item.getAttribute("aria-checked") === expected) return;
      item.setAttribute("aria-checked", expected);
      item.dispatchEvent(new CustomEvent("segmented:refresh", { bubbles: true }));
    });
  };

  const setChoice = (choice) => {
    if (choice === "system") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, choice);
    apply(choice);
    refreshButtons();
  };

  // Re-resolve when OS preference flips, but only if the user is on "system".
  media.addEventListener("change", () => {
    if (getChoice() === "system") apply("system");
  });

  document.addEventListener("click", (event) => {
    const item = event.target.closest("[data-theme-set]");
    if (!item) return;
    event.preventDefault();
    setChoice(item.dataset.themeSet);
  });

  refreshButtons();
  document.addEventListener("htmx:afterSwap", refreshButtons);
})();
