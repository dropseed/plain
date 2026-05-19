(() => {
  const script = document.currentScript;
  if (!script) return;

  // Guard against double-injection — patching pushState twice would
  // multiply every navigation event.
  if (window.__plainPageviews) return;
  window.__plainPageviews = true;

  const token = script.dataset.token;
  const pageviewsUrl = script.dataset.pageviewsUrl;
  if (!token || !pageviewsUrl) return;

  const identity = script.dataset.identity || "";
  const initialTraceId = script.dataset.traceId || "";
  const initialRoute = script.dataset.route || "";

  const ANONYMOUS_ID_KEY = "plain_pageviews_anonymous_id";

  function anonymousId() {
    try {
      let id = localStorage.getItem(ANONYMOUS_ID_KEY);
      if (!id) {
        id = crypto.randomUUID();
        localStorage.setItem(ANONYMOUS_ID_KEY, id);
      }
      return id;
    } catch {
      // localStorage unavailable (private mode, blocked storage, etc.)
      return "";
    }
  }

  const anonId = anonymousId();
  let isInitialView = true;
  let lastUrl = "";

  function send() {
    if (location.href === lastUrl) return;

    const payload = {
      token,
      url: location.href,
      title: document.title,
      referrer: isInitialView ? document.referrer : lastUrl,
      anonymous_id: anonId,
      identity,
      // Only the server-rendered initial load has a backend trace and a
      // resolved route pattern; SPA navigations land with both blank.
      trace_id: isInitialView ? initialTraceId : "",
      route: isInitialView ? initialRoute : "",
    };

    lastUrl = location.href;
    isInitialView = false;

    try {
      navigator.sendBeacon(pageviewsUrl, JSON.stringify(payload));
    } catch {
      // sendBeacon unsupported or blocked — drop the event.
    }
  }

  send();

  // SPA navigations: History pushState + back/forward.
  const originalPushState = history.pushState;
  history.pushState = function (...args) {
    const result = originalPushState.apply(this, args);
    setTimeout(send, 0);
    return result;
  };
  window.addEventListener("popstate", () => setTimeout(send, 0));
})();
