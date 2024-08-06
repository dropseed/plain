// Make this available to the JS console for the user
var plainToolbar = {
  hide: function () {
    // Hide by inserting a style so it doesn't flash on page load
    var style = document.createElement("style");
    style.innerHTML = "#plaintoolbar { display: none; }";
    document.getElementsByTagName("head")[0].appendChild(style);
    this.stylesheet = style;
  },
  show: function () {
    localStorage.removeItem("plaintoolbar.hidden_until");
    if (this.stylesheet) {
      this.stylesheet.remove();
    }
  },
  shouldHide: function () {
    var hiddenUntil = localStorage.getItem("plaintoolbar.hidden_until");
    if (hiddenUntil) {
      if (Date.now() < hiddenUntil) {
        return true;
      } else {
        localStorage.removeItem("plaintoolbar.hidden_until");
        return false;
      }
    }
    return false;
  },
  hideUntil: function (until) {
    localStorage.setItem("plaintoolbar.hidden_until", until);
    this.hide();
  },
  toggleExpand: function () {
    this.expanded = !this.expanded;
    document.querySelector("#plaintoolbar-details").classList.toggle("hidden");
  },
};

// Render it hidden immediately if the user has hidden it before
if (plainToolbar.shouldHide()) {
  plainToolbar.hide();
}

window.addEventListener("load", function () {
    document.querySelector('[data-plaintoolbar-hide]').addEventListener('click', function() {
        console.log("Hiding staff toolbar for 1 hour");
        plainToolbar.hideUntil(Date.now() + 3600000);
    });
    document.querySelector('[data-plaintoolbar-expand]').addEventListener('click', function() {
        plainToolbar.toggleExpand();
    });
});
