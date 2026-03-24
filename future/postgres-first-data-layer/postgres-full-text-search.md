---
related:
  - postgres-native-orm
depends_on:
  - postgres-native-schema
---

# Full-text search

PostgreSQL's native full-text search covers ~80-90% of search use cases without external infrastructure. Users should only reach for Elasticsearch/Typesense/Meilisearch when they need features like typo tolerance, faceted search, or massive scale. Plain has zero FTS support today.

## The 80/20 split

Full-text search spans the boundary between the ORM's 80% layer and the SQL 20% layer. The right split:

**Schema layer** (declare on models):

- `SearchVectorField` — a generated column holding a `tsvector`, auto-maintained by Postgres
- GIN index on the search vector (depends on `postgres-native-schema`)

**80% ORM layer** (common single-table search):

- A `.search()` lookup or method that wraps `websearch_to_tsquery` — the simplest, most user-friendly query function (handles quotes, minus signs, OR operators like Google search)
- Basic ranking by relevance

**20% SQL layer** (via `sql()`):

- Custom ranking with `ts_rank` normalization options (document length, etc.)
- Weighted multi-column search (`set_weight` with A/B/C/D grades)
- `ts_headline` for highlighting matched terms in results
- Custom language configurations
- Combining FTS with vector similarity or other scoring

## Schema: SearchVectorField

A generated column that maintains a `tsvector` from one or more source columns:

```python
class Article(models.Model):
    title = TextField()
    body = TextField()
    search_vector = SearchVectorField(
        columns=["title", "body"],
        language="english",
    )

    class Meta:
        indexes = [
            Index(fields=["search_vector"], type="gin"),
        ]
```

Under the hood, this generates:

```sql
search_vector tsvector GENERATED ALWAYS AS (
    set_weight(to_tsvector('english', coalesce(title, '')), 'A') ||
    to_tsvector('english', coalesce(body, ''))
) STORED
```

Design decisions:

- **Language must be explicit** — `to_tsvector` without a language config is not immutable, which Postgres requires for generated columns
- **COALESCE wrapping** — prevents NULL source columns from nullifying the entire vector
- **Weighting**: First column gets weight 'A' (highest), subsequent columns get lower weights. This means title matches rank higher than body matches by default. Could accept explicit weights: `columns=[("title", "A"), ("body", "B")]`
- **Single-column shorthand**: `SearchVectorField(columns=["body"])` for simple cases

This depends on `postgres-native-schema` for generated column and GIN index support.

## ORM: search lookup

The simplest useful search — one method, uses `websearch_to_tsquery` which handles natural user input:

```python
# Basic search
results = Article.query.where(
    Article.search_vector.search("python web framework")
)

# With ranking (order by relevance)
results = Article.query.where(
    Article.search_vector.search("python web framework")
).order_by(Article.search_vector.rank("python web framework"))
```

`websearch_to_tsquery` is the right default because:

- It accepts natural language input (no special syntax required)
- It supports Google-style operators: `"exact phrase"`, `-exclude`, `OR`
- It's fault-tolerant — messy user input doesn't throw syntax errors
- It covers the vast majority of search bar use cases

The alternatives (`plainto_tsquery`, `phraseto_tsquery`, `to_tsquery`) are available via `sql()` for users who need them.

## SQL layer: advanced search

For ranking customization, highlighting, and complex scoring — use `sql()`:

```python
# Weighted ranking with document length normalization
results = Article.query.sql("""
    SELECT {Article.*},
        ts_rank(
            {Article.search_vector},
            websearch_to_tsquery('english', {query}),
            1  -- normalize by document length
        ) AS rank
    FROM {Article}
    WHERE {Article.search_vector} @@ websearch_to_tsquery('english', {query})
    ORDER BY rank DESC
""", query=user_input, result_type=Article)

# Highlighting matched terms
results = Article.query.sql("""
    SELECT {Article.*},
        ts_headline('english', {Article.title}, websearch_to_tsquery('english', {query}),
            'StartSel=<mark>, StopSel=</mark>') AS highlighted_title,
        ts_headline('english', {Article.body}, websearch_to_tsquery('english', {query}),
            'StartSel=<mark>, StopSel=</mark>, MaxFragments=3') AS highlighted_body
    FROM {Article}
    WHERE {Article.search_vector} @@ websearch_to_tsquery('english', {query})
    ORDER BY ts_rank({Article.search_vector}, websearch_to_tsquery('english', {query})) DESC
""", query=user_input)
```

This is inherently SQL territory — ranking normalization, headline formatting, and custom scoring involve too many knobs to wrap cleanly in Python.

## What we're NOT building

- **LIKE/ILIKE wrappers** — these already work via existing lookups (`contains`, `icontains`, `startswith`, etc.). They're fine for simple pattern matching but not for search.
- **Trigram search** (`pg_trgm`) — useful for fuzzy matching and typo tolerance, but a separate concern from FTS. Could be a future exploration.
- **External search engine integration** — out of scope. Users who need Elasticsearch/Typesense should integrate directly.

## Open questions

1. **Should `SearchVectorField` be a generated column or a trigger-maintained column?** Generated columns are cleaner (no trigger management) but have restrictions: can't reference other tables, expression must be immutable. Trigger-based is more flexible but more complex. Generated column covers the common case; users with exotic needs can use `RunSQL`.

2. **How should the `.search()` lookup compose with other filters?** It should be a normal lookup that participates in `where()` chains: `Article.query.where(Article.search_vector.search("query"), Article.is_published.eq(True))`.

3. **Should ranking be a separate concept or baked into search?** Keeping them separate (search for filtering, rank for ordering) is more composable. But users will almost always want both together.

4. **Language configuration** — hardcoded per field, or configurable at query time? Per-field is simpler and covers most apps (single language). Multi-language apps are the `sql()` case.
