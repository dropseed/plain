(() => {
  // Find the current <script> tag that included this file
  const scriptTag = document.currentScript;

  if (!scriptTag) {
    console.error("Analytics script must be included using a <script> tag.");
    return;
  }

  // Get the tracking URL from the data-track-url attribute
  let trackUrl = scriptTag.getAttribute("data-track-url");

  if (!trackUrl) {
    const defaultTrackPath = "/pageviews/track/";
    try {
      const scriptUrl = new URL(scriptTag.src);
      trackUrl = `${scriptUrl.origin}${defaultTrackPath}`;
    } catch (_error) {
      trackUrl = defaultTrackPath;
    }
  }

  // Function to send a pageview event using the Beacon API
  const data = {
    url: window.location.href, // Current page URL
    title: document.title, // Current page title
    referrer: document.referrer, // Referring URL
    timestamp: new Date().toISOString(), // ISO 8601 timestamp
  };

  // So we can send the content type header
  const dataBlob = new Blob([JSON.stringify(data)], {
    type: "application/json",
  });

  try {
    const success = navigator.sendBeacon(trackUrl, dataBlob);
    if (!success) {
      console.warn("Beacon API failed to send pageview event.");
    }
  } catch (error) {
    console.error("Error sending pageview event:", error);
  }
})();
