const container = document.createElement("div");
document.currentScript.parentNode.insertBefore(
  container,
  document.currentScript,
);

// Build the iframe url based on the script src
// (replace the .js extension with /iframe/)
const src = document.currentScript.src;
const origin = new URL(src).origin;
const iframeSrc = src.replace(/\.js$/, "/iframe/");

const iframe = document.createElement("iframe");
iframe.src = iframeSrc;
iframe.width = "100%";
iframe.height = "auto";
iframe.style.border = "none";
iframe.style.display = "none";

// Insert or select a loading div
let loading;
const loadingData = document.currentScript.getAttribute("data-loading");
if (!loadingData) {
  const svg =
    '<svg width="40px" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><circle fill="none" stroke-opacity="1" stroke="#000000" stroke-width=".5" cx="100" cy="100" r="0"><animate attributeName="r" calcMode="spline" dur="1" values="1;80" keyTimes="0;1" keySplines="0 .2 .5 1" repeatCount="indefinite"></animate><animate attributeName="stroke-width" calcMode="spline" dur="1" values="0;25" keyTimes="0;1" keySplines="0 .2 .5 1" repeatCount="indefinite"></animate><animate attributeName="stroke-opacity" calcMode="spline" dur="1" values="1;0" keyTimes="0;1" keySplines="0 .2 .5 1" repeatCount="indefinite"></animate></circle></svg>';
  loading = document.createElement("div");
  loading.style.display = "flex";
  loading.style.justifyContent = "center";
  loading.innerHTML = svg;
} else if (loadingData.startsWith("#")) {
  loading = document.querySelector(loadingData);
} else if (!loading) {
  loading = document.createElement("div");
  loading.textContent = loadingData;
  loading.style.color = "black";
}
container.appendChild(loading);

// Insert or select an error div
let error;
const errorData = document.currentScript.getAttribute("data-error");
if (!errorData) {
  error = document.createElement("div");
  error.textContent = "There was an error. Please email us directly.";
  error.style.color = "black";
  error.style.display = "none";
} else if (errorData.startsWith("#")) {
  error = document.querySelector(errorData);
  error.style.display = "none";
} else {
  error = document.createElement("div");
  error.textContent = errorData;
  error.style.color = "black";
  error.style.display = "none";
}
container.appendChild(error);

// Keep track of whether the iframe has told us it is loaded
let iframeLoaded = false;

// Listen for postMessage events from the iframe
window.addEventListener("message", (event) => {
  if (event.origin !== origin) {
    return;
  }

  if (event.data.type === "setHeight") {
    iframe.style.height = `${event.data.height}px`;
  } else if (event.data.type === "iframeLoaded") {
    // The iframe has loaded, show it
    iframe.style.display = "block";
    loading.style.display = "none";

    iframeLoaded = true;

    error.style.display = "none";
    loading.style.display = "none";
    iframe.style.display = "block";
  }
});

iframe.onload = () => {
  iframeLoaded = false; // Make sure subsequent loads are treated as new

  error.style.display = "none";
  loading.style.display = "flex";
  iframe.style.display = "none";

  // If the iframe hasn't send a loaded message after 10 seconds, render an error emssage
  setTimeout(() => {
    if (!iframeLoaded) {
      error.style.display = "block";
      loading.style.display = "none";
      iframe.style.display = "none";
    }
  }, 10000);
};

container.appendChild(iframe);
