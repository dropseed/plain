/*
 * Plain admin theme toggle.
 *
 * Stores the user's choice in localStorage under "plain-admin-theme" with
 * one of three values: "light", "dark", or "system" (default). The
 * `<html>` element gets a `dark` class when the resolved theme is dark.
 *
 * The no-flash init runs as an inline script in <head> before any markup
 * paints — see base.html. This file wires up the toggle button and the
 * `prefers-color-scheme` media query listener.
 */

(() => {
  const STORAGE_KEY = "plain-admin-theme";
  const root = document.documentElement;
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  const getStoredChoice = () => {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  };

  const resolve = (choice) => {
    if (choice === "system") {
      return media.matches ? "dark" : "light";
    }
    return choice;
  };

  const apply = (choice) => {
    const theme = resolve(choice);
    root.classList.toggle("dark", theme === "dark");
    root.dataset.themeChoice = choice;
    root.dataset.themeResolved = theme;
  };

  const setChoice = (choice) => {
    if (choice === "system") {
      localStorage.removeItem(STORAGE_KEY);
    } else {
      localStorage.setItem(STORAGE_KEY, choice);
    }
    apply(choice);
    refreshButtons();
  };

  const refreshButtons = () => {
    const choice = getStoredChoice();
    document.querySelectorAll("[data-theme-set]").forEach((item) => {
      item.setAttribute("aria-checked", item.dataset.themeSet === choice ? "true" : "false");
    });
  };

  // Re-apply when the OS preference changes and the user is on "system".
  media.addEventListener("change", () => {
    if (getStoredChoice() === "system") {
      apply("system");
    }
  });

  document.addEventListener("click", (event) => {
    const item = event.target.closest("[data-theme-set]");
    if (!item) return;
    event.preventDefault();
    setChoice(item.dataset.themeSet);
  });

  // First paint is handled by the inline init in <head>; this just makes
  // sure any toggle buttons rendered on initial load show the right state.
  refreshButtons();
  document.addEventListener("htmx:afterSwap", refreshButtons);
})();
