/*
 * data-autosubmit — submit the enclosing form on `change`. Used for
 * list filters and pagination dropdowns where the user shouldn't have
 * to hit a separate submit button.
 *
 * Also intercepts every `<form method="GET">` submission so empty
 * params get stripped from the URL — keeps list views from
 * accumulating `?q=&filter=` cruft when filters are cleared.
 */
jQuery(($) => {
  function submitFormClean(form) {
    const formData = new FormData(form);
    const params = new URLSearchParams();
    for (const [key, value] of formData.entries()) {
      if (value) {
        params.append(key, value);
      }
    }
    const basePath = form.getAttribute("action") || window.location.pathname;
    const url = params.toString() ? `${basePath}?${params.toString()}` : basePath;
    window.location.href = url;
  }

  $(document).on("change", "[data-autosubmit]", function (_e) {
    submitFormClean($(this).closest("form")[0]);
  });

  $(document).on("submit", "form[method='GET']", function (e) {
    e.preventDefault();
    submitFormClean(this);
  });
});
