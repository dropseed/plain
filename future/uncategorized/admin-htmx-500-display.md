# Admin: display htmx boost 500 errors

`admin.js` has `htmx:responseError` handling that shows an `alert()` with a generic message. For boosted links that 500, the HTML error body (which might have useful debug info) is never displayed. Could render the error response in a modal or inline panel instead.
