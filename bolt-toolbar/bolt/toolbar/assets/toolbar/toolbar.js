// Make this available to the JS console for the user
var boltToolbar = {
  hide: function () {
    // Hide by inserting a style so it doesn't flash on page load
    var style = document.createElement("style");
    style.innerHTML = "#bolttoolbar { display: none; }";
    document.getElementsByTagName("head")[0].appendChild(style);
    this.stylesheet = style;
  },
  show: function () {
    localStorage.removeItem("bolttoolbar.hidden_until");
    if (this.stylesheet) {
      this.stylesheet.remove();
    }
  },
  shouldHide: function () {
    var hiddenUntil = localStorage.getItem("bolttoolbar.hidden_until");
    if (hiddenUntil) {
      if (Date.now() < hiddenUntil) {
        return true;
      } else {
        localStorage.removeItem("bolttoolbar.hidden_until");
        return false;
      }
    }
    return false;
  },
  hideUntil: function (until) {
    localStorage.setItem("bolttoolbar.hidden_until", until);
    this.hide();
  },
};

// Render it hidden immediately if the user has hidden it before
if (boltToolbar.shouldHide()) {
  boltToolbar.hide();
}

window.addEventListener("load", function () {
    document.querySelector('[data-bolttoolbar-hide]').addEventListener('click', function() {
        console.log("Hiding staff toolbar for 1 hour");
        boltToolbar.hideUntil(Date.now() + 3600000);
    });
});
