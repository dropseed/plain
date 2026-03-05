# plain-models: Tie related_query_name to reverse descriptors

**Make reverse ORM filtering use the explicit `ReverseForeignKey`/`ReverseManyToMany` descriptor name instead of an independent `related_query_name` parameter.**

## Problem

Plain removed Django's `related_name` — reverse attribute access requires explicit `ReverseForeignKey`/`ReverseManyToMany` descriptors. But `related_query_name` still exists as a separate, user-settable parameter on `ForeignKeyField` and `ManyToManyField`. This creates two problems:

- **Inconsistency**: You can filter across a reverse relation you never explicitly declared (`Parent.query.filter(childcascade__name="...")`)
- **Name mismatch**: The filter name (model name like `childcascade`) doesn't match the descriptor name (like `childcascade_set` or `children`)

## Solution

1. Remove the `related_query_name` parameter from `ForeignKeyField` and `ManyToManyField`
2. When a `ReverseForeignKey`/`ReverseManyToMany` is declared, use its attribute name as the reverse query name
3. When no descriptor is declared, the model-name default continues working for internal ORM operations

### Example

```python
class Author(Model):
    name: str = CharField(max_length=100)
    books: ReverseForeignKey[Book] = ReverseForeignKey(to="Book", field="author")

class Book(Model):
    title: str = CharField(max_length=200)
    author: Author = ForeignKeyField(Author, on_delete=CASCADE)
```

Before: `Author.query.filter(book__title="...")` (implicit model name)
After: `Author.query.filter(books__title="...")` (matches the descriptor name)

## How it works internally

`RelatedField.related_query_name()` returns `self.remote_field.related_query_name or self.model.model_options.model_name`. This value is used throughout the ORM for JOINs, caching, prefetching, and validation — not just user-facing filtering.

The reverse descriptor sets `remote_field.related_query_name` to its attribute name during `lazy_related_operation` resolution. When no descriptor exists, the method falls back to the model name. All internal consumers call `related_query_name()` and get a valid name either way:

| Internal use                        | Location                         | Impact                                                                                       |
| ----------------------------------- | -------------------------------- | -------------------------------------------------------------------------------------------- |
| `ForeignObjectRel.name`             | `reverse_related.py:88`          | Returns descriptor name when declared, model name otherwise. Cache invalidated during setup. |
| `ForeignObjectRel.get_cache_name()` | `reverse_related.py:203`         | Prefetch cache key. Uses whatever name `related_query_name()` returns.                       |
| SQL compiler `select_related`       | `sql/compiler.py:1022,1119,1145` | Resolves reverse relations to JOINs. `select_related("books")` works with descriptor.        |
| `select_related_descend()`          | `query_utils.py:352`             | Checks if reverse relation was requested by name. Same behavior.                             |
| Forward FK prefetch                 | `related_descriptors.py:113`     | Builds `{query_name__in: instances}` filter. Unaffected.                                     |
| M2M manager init                    | `related_managers.py:338,345`    | Sets prefetch cache and query field names. Uses current `related_query_name()`.              |
| Ordering/prepare validation         | `base.py:1247`                   | Validates field names. Uses `related_query_name()` for reverse fields.                       |
| Clash detection                     | `related.py:187`                 | Checks name collisions against descriptor name or model name.                                |

## Changes

**`plain-models/plain/models/fields/reverse_descriptors.py`** — Core change: `resolve_related_field` sets `remote_field.related_query_name` to descriptor name, invalidates `ForeignObjectRel.name` cache, expires Meta reverse cache.

**`plain-models/plain/models/fields/related.py`** — Remove `related_query_name` param from `RelatedField.__init__`, `ForeignKeyField.__init__`, `ManyToManyField.__init__`. Remove `%(class)s` template formatting (dead code — Plain has no model inheritance). Remove from `deconstruct()`. Update preflight error messages.

**`plain-models/plain/models/fields/reverse_related.py`** — Remove `related_query_name` param from `ForeignObjectRel.__init__`, `ForeignKeyRel.__init__`, `ManyToManyRel.__init__`. Init as `None`.

**`plain-models/plain/models/fields/__init__.py`** — Remove `"related_query_name"` from `non_db_attrs`.

**`plain-models/plain/models/types.pyi`** — Remove `related_query_name` from type stubs.
