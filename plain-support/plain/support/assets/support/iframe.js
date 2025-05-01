document.addEventListener("DOMContentLoaded", () => {
  function sendHeight(height) {
    window.parent.postMessage({ type: "setHeight", height: height }, "*");
  }

  let lastHeight = 0;

  function calculateAndSendHeight() {
    const height = document.documentElement.scrollHeight;
    if (height !== lastHeight) {
      lastHeight = height;
      sendHeight(height);
    }
  }

  // Observe DOM changes
  const observer = new MutationObserver(calculateAndSendHeight);
  observer.observe(document.body, { childList: true, subtree: true });

  // Recalculate height on window resize
  window.addEventListener("resize", calculateAndSendHeight);

  // Send initial height
  calculateAndSendHeight();

  // Tell the embed.js that we loaded the iframe successfully (no other good way to do this)
  window.parent.postMessage({ type: "iframeLoaded" }, "*");
});
