jQuery(function ($) {
  var $actionCheckbox = $("[data-action-checkbox]");
  var $actionPks = $('[name="action_pks"]');
  var $actionSelect = $('[name="action_key"]');
  var $actionSubmit = $('[data-actions-form] [type="submit"]');

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

  // TODO Enable shift-clicking to select a range of checkboxes
});
