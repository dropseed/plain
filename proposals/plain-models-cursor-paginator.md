# plain-models: CursorPaginator

- Add `CursorPaginator` class in `plain-models/plain/models/paginator.py` (new file)
- Complements core [`Paginator`](/plain/plain/paginator.py) (offset-based)
- Plain core doesn't know about databases, so cursor pagination belongs in plain-models
- Uses keyset pagination: encodes field values as cursor, builds WHERE clauses for next page
- Common use cases: infinite scroll, API pagination, real-time feeds, large datasets
- Better performance than offset/limit for deep pagination (doesn't scan skipped rows)
- Usage example:

    ```python
    from plain.models.paginator import CursorPaginator

    queryset = Article.query.order_by("-created_at", "id")
    paginator = CursorPaginator(queryset, per_page=20)

    page = paginator.page(after=cursor_token)

    for article in page:
        print(article.title)

    if page.has_next():
        next_page = paginator.page(after=page.end_cursor)
    ```

- Implementation challenges:
    - Building WHERE clauses for multi-field ordering (complex)
    - Cursor encoding/decoding (base64 JSON)
    - Type serialization for dates, UUIDs, etc.
    - Cross-database compatibility (SQLite doesn't support tuple comparison)

- API considerations:
    - `CursorPage` with `.has_next()`, `.has_previous()`, `.start_cursor`, `.end_cursor`
    - No `.count()` or page numbers (defeats cursor pagination benefits)
    - Error handling for invalid cursors, missing ordering, etc.

- Implementation details TBD
