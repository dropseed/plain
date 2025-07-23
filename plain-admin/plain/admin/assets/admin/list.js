jQuery(($) => {
  const SENTINEL_ALL = "__all__";

  const $actionCheckbox = $("[data-action-checkbox]");
  const $actionCheckboxHeader = $("[data-action-checkbox-all]");
  const $actionIds = $('[name="action_ids"]');
  const $actionSelect = $('[name="action_name"]');
  const $actionForm = $("[data-actions-form]");
  let $lastActionCheckboxChecked = null;

  $actionCheckbox.on("change", () => {
    if ($actionCheckboxHeader.is(":checked")) {
      // If header is checked and a row changes, uncheck header
      if (
        $actionCheckbox.filter(":checked").length !== $actionCheckbox.length
      ) {
        $actionCheckboxHeader.prop("checked", false);
      }
    }
    updateActionIds();
  });

  $actionCheckboxHeader.on("change", () => {
    const checked = $actionCheckboxHeader.is(":checked");
    $actionCheckbox.prop("checked", checked);
    updateActionIds();
  });

  function updateActionIds() {
    if ($actionCheckboxHeader.is(":checked")) {
      $actionIds.val(SENTINEL_ALL);
    } else {
      const ids = [];
      $actionCheckbox.each(function () {
        if ($(this).is(":checked")) {
          ids.push($(this).attr("name"));
        }
      });
      $actionIds.val(ids.join(","));
    }
  }

  $actionSelect.on("change", () => {
    if ($actionSelect.val()) {
      const actionName = $actionSelect.val();
      let confirmMessage;

      if ($actionIds.val() === SENTINEL_ALL) {
        // All items selected
        confirmMessage = `Are you sure you want to perform "${actionName}" on ALL items across all pages?`;
      } else if ($actionIds.val()) {
        // Specific items selected
        const selectedCount = $actionIds.val().split(",").length;
        const itemText = selectedCount === 1 ? "item" : "items";
        confirmMessage = `Are you sure you want to perform "${actionName}" on ${selectedCount} selected ${itemText}?`;
      } else {
        // Action without selected items (bulk action)
        confirmMessage = `Are you sure you want to perform "${actionName}"?`;
      }

      if (confirm(confirmMessage)) {
        $actionForm.submit();
      } else {
        $actionSelect.val(""); // Reset the select if cancelled
      }
    }
  });

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
