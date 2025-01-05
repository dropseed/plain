(function () {
  // Find the current <script> tag that included this file
  const scriptTag = document.currentScript;

  if (!scriptTag) {
    console.error("Analytics script must be included using a <script> tag.");
    return;
  }

  // Get the tracking URL from the data-track-url attribute
  const trackUrl = scriptTag.getAttribute("data-track-url");

  if (!trackUrl) {
    console.error("Missing 'data-track-url' attribute in the <script> tag.");
    return;
  }

  // Function to send a pageview event using the Beacon API
    const data = {
        url: window.location.href, // Current page URL
        title: document.title, // Current page title
        referrer: document.referrer, // Referring URL
        timestamp: new Date().toISOString(), // ISO 8601 timestamp
    };

    try {
        const success = navigator.sendBeacon(trackUrl, JSON.stringify(data));
        if (!success) {
        console.warn("Beacon API failed to send pageview event.");
        }
    } catch (error) {
        console.error("Error sending pageview event:", error);
    }
})();