---
labels:
- plain-postgres
related:
- listview-pagination
---

# plain-postgres: CursorPaginator

- Add `CursorPaginator` class in `plain-postgres/plain/postgres/paginator.py` (new file)
- Complements core [`Paginator`](/plain/plain/paginator.py) (offset-based)
- Plain core doesn't know about databases, so cursor pagination belongs in plain-postgres
- Uses keyset pagination: encodes field values as cursor, builds WHERE clauses for next page
- Common use cases: infinite scroll, API pagination, real-time feeds, large datasets
- Better performance than offset/limit for deep pagination (doesn't scan skipped rows)
- Usage example:

    ```python
    from plain.postgres.paginator import CursorPaginator

    queryset = Article.query.order_by("-created_at", "id")
    paginator = CursorPaginator(queryset, per_page=20)

    page = paginator.page(after=cursor_token)

    for article in page:
        print(article.title)

    if page.has_next():
        next_page = paginator.page(after=page.end_cursor)
    ```

- **Row value syntax** is the underlying mechanism for efficient multi-column cursor comparison. Instead of complex nested OR logic for multi-field ordering:

    ```sql
    -- Naive approach (complex, error-prone)
    WHERE (first_name > 'Aliyah')
       OR (first_name = 'Aliyah' AND last_name > 'Bashirian')
       OR (first_name = 'Aliyah' AND last_name = 'Bashirian' AND id > 322714)

    -- Row value syntax (single clean expression)
    WHERE (first_name, last_name, id) > ('Aliyah', 'Bashirian', 322714)
    ```

    Postgres handles the tuple comparison correctly, including NULL handling. This drastically simplifies the implementation — the paginator only needs to build a single row value comparison, not nested OR chains that grow with each sort field.

- Implementation challenges:
    - ~~Building WHERE clauses for multi-field ordering (complex)~~ — row value syntax solves this
    - Cursor encoding/decoding (base64 JSON)
    - Type serialization for dates, UUIDs, etc.

- API considerations:
    - `CursorPage` with `.has_next()`, `.has_previous()`, `.start_cursor`, `.end_cursor`
    - No `.count()` or page numbers (defeats cursor pagination benefits)
    - Error handling for invalid cursors, missing ordering, etc.

- Implementation details TBD
