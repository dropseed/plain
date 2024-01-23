jQuery(function ($) {
  var $actionCheckbox = $("[data-action-checkbox]");
  var $actionPks = $('[name="action_pks"]');
  var $actionSelect = $('[name="action_name"]');
  var $actionSubmit = $('[data-actions-form] [type="submit"]');
  var $lastActionCheckboxChecked = null;

  $actionCheckbox.on("change", function () {
    var pks = [];
    $actionCheckbox.each(function () {
      if ($(this).is(":checked")) {
        pks.push($(this).attr("name"));
      }
    });
    $actionPks.val(pks.join(","));

    updateActionSubmit();
  });

  $actionSelect.on("change", function () {
    updateActionSubmit();
  });

  function updateActionSubmit() {
    if ($actionPks.val() && $actionSelect.val()) {
      // We've chosen an action
      $actionSubmit.prop("disabled", false);
    } else {
      $actionSubmit.prop("disabled", true);
    }
  }

  // Enable shift-clicking to select a range of checkboxes
  $actionCheckbox.on("click", function (e) {
    if (e.shiftKey) {
      var $this = $(this);
      var thisIndex = $actionCheckbox.index($this);
      var lastIndex = $actionCheckbox.index($lastActionCheckboxChecked);
      var minIndex = Math.min(thisIndex, lastIndex);
      var maxIndex = Math.max(thisIndex, lastIndex);
      var $checkboxes = $actionCheckbox.slice(minIndex, maxIndex + 1);
      $checkboxes.prop("checked", $this.is(":checked"));
    } else {
      $lastActionCheckboxChecked = $(this);
    }
  });

  // Merge query params with the current url and the link url
  $("[data-merge-params]").each(function () {
    var currentUrl = new URL(window.location.href);
    var params = new URL($(this).attr("href"), window.location.href).searchParams;
    params.forEach(function (value, key) {
      currentUrl.searchParams.set(key, value);
    });
    $(this).attr("href", currentUrl.toString());
  });
});
