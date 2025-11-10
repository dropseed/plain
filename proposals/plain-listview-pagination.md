# plain: ListView pagination support

- Add optional `paginator` parameter to [`ListView`](/plain/plain/views/objects.py#L148)
- Defaults to `None` (no pagination, current behavior)
- When provided, automatically handles pagination and adds page object to context
- Works with both offset-based `Paginator` and cursor-based `CursorPaginator`
- Usage example:

    ```python
    from plain.views import ListView
    from plain.paginator import Paginator

    class ArticleListView(ListView):
        paginator = Paginator(per_page=20)

        def get_objects(self):
            return Article.query.order_by("-created_at")

    # Or with CursorPaginator
    from plain.models.paginator import CursorPaginator

    class ArticleListView(ListView):
        paginator = CursorPaginator(per_page=20)

        def get_objects(self):
            return Article.query.order_by("-created_at", "id")
    ```

- Template context would include `page` object instead of/in addition to `objects`
- ListView handles reading page parameter from request (e.g., `?page=2` or `?after=cursor`)
- Implementation details TBD (parameter names for cursors, error handling, context naming, etc.)
