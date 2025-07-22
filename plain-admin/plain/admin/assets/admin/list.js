jQuery(($) => {
  const $actionCheckbox = $("[data-action-checkbox]");
  const $actionIds = $('[name="action_ids"]');
  const $actionSelect = $('[name="action_name"]');
  const $actionSubmit = $('[data-actions-form] [type="submit"]');
  let $lastActionCheckboxChecked = null;

  $actionCheckbox.on("change", () => {
    const ids = [];
    $actionCheckbox.each(function () {
      if ($(this).is(":checked")) {
        ids.push($(this).attr("name"));
      }
    });
    $actionIds.val(ids.join(","));

    updateActionSubmit();
  });

  $actionSelect.on("change", () => {
    updateActionSubmit();
  });

  function updateActionSubmit() {
    if ($actionIds.val() && $actionSelect.val()) {
      // We've chosen an action
      $actionSubmit.prop("disabled", false);
    } else {
      $actionSubmit.prop("disabled", true);
    }
  }

  // Enable shift-clicking to select a range of checkboxes
  $actionCheckbox.on("click", function (e) {
    if (e.shiftKey) {
      const $this = $(this);
      const thisIndex = $actionCheckbox.index($this);
      const lastIndex = $actionCheckbox.index($lastActionCheckboxChecked);
      const minIndex = Math.min(thisIndex, lastIndex);
      const maxIndex = Math.max(thisIndex, lastIndex);
      const $checkboxes = $actionCheckbox.slice(minIndex, maxIndex + 1);
      $checkboxes.prop("checked", $this.is(":checked"));
    } else {
      $lastActionCheckboxChecked = $(this);
    }
  });

  // Merge query params with the current url and the link url
  $("[data-merge-params]").each(function () {
    const currentUrl = new URL(window.location.href);
    const params = new URL($(this).attr("href"), window.location.href)
      .searchParams;
    params.forEach((value, key) => {
      currentUrl.searchParams.set(key, value);
    });
    $(this).attr("href", currentUrl.toString());
  });
});
