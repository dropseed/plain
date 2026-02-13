# Database & Models

## Schema Changes

When creating new models or modifying existing model fields/relationships, always enter plan mode first. Database schema is hard to change after the fact, so get the design right before writing code.

In your plan, present:

- Proposed schema as a table (model, field, type, constraints)
- Relationship cardinality (1:1, 1:N, M:N)
- Key decisions: nullable vs default, indexing, cascade behavior
- Whether the data could live on an existing model instead of a new one

Get approval before writing any model code or generating migrations.

## Migrations

### Creating Migrations

```
uv run plain makemigrations
```

Key flags:

- `--dry-run` — Show what migrations would be created (with operations and SQL) without writing files
- `--check` — Exit non-zero if migrations are needed (for CI)
- `--empty <package>` — Create an empty migration for custom data migrations
- `--name <name>` — Set the migration filename
- `-v 3` — Show full migration file contents

Only write migrations by hand if they are custom data migrations.

### Running Migrations

```
uv run plain migrate --backup
```

Key flags:

- `--backup` / `--no-backup` — Create a database backup before applying (default: on in DEBUG)
- `--plan` — Show what migrations would run without applying them
- `--check` — Exit non-zero if unapplied migrations exist (for CI)
- `--fake` — Mark migrations as applied without running them

### Viewing Migration Status

```
uv run plain migrations list
```

`migrate` has no `--list` or `--status` flag. Use `plain migrations list`.

- `--format plan` — Show in dependency order instead of grouped by package

### Other Migration Commands

- `uv run plain migrations squash <package> <migration>` — Squash migrations into one
- `uv run plain migrations prune` — Remove stale migration records

Run `uv run plain docs models --source` for detailed model and migration documentation.

## Querying

Use `Model.query` to build querysets:

- `User.query.all()`
- `User.query.filter(is_active=True)`
- `User.query.get(pk=1)`
- `User.query.exclude(role="admin")`

Run `uv run plain docs models --api` for the full query API.

## Best Practices

### CRITICAL — N+1 Query Prevention

### Use `select_related` for ForeignKey access in loops

Accessing a FK in a loop without `select_related()` fires one query per row.

```python
# Bad — N+1 queries
for post in Post.query.all():
    print(post.author.name)

# Good — single JOIN
for post in Post.query.select_related("author").all():
    print(post.author.name)
```

### Use `prefetch_related` for reverse/M2N access in loops

Reverse ForeignKey and ManyToMany relations need a separate prefetch query.

```python
# Bad — N+1 queries
for author in Author.query.all():
    print(author.posts.count())

# Good — one extra query
for author in Author.query.prefetch_related("posts").all():
    print(author.posts.count())
```

### Annotate instead of per-row aggregations

Use database-level aggregation instead of calling `.count()` or similar per row.

```python
# Bad — N+1 queries
for category in Category.query.all():
    print(category.products.count())

# Good — single query with annotation
from plain.models.aggregates import Count
for category in Category.query.annotate(num_products=Count("products")).all():
    print(category.num_products)
```

### Fetch all data in the view

Templates should only render data, never trigger queries. Prepare everything in the view.

```python
# Bad — template triggers lazy queries
def get_template_context(self):
    return {"posts": Post.query.all()}  # related lookups happen in template

# Good — eagerly load everything
def get_template_context(self):
    return {"posts": Post.query.select_related("author").prefetch_related("tags").all()}
```

### Use `.values_list()` when you only need specific columns

Avoid loading full model instances when you only need one or two fields.

```python
# Bad — loads entire model objects
emails = [u.email for u in User.query.all()]

# Good — single column, flat list
emails = list(User.query.values_list("email", flat=True))
```

### CRITICAL — Schema Design

### Index fields used in filters and ordering

Add indexes for columns that appear in `.filter()`, `.order_by()`, or `.exclude()`.

```python
# Bad — full table scan on every filtered query
class Order(models.Model):
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()

# Good — indexed for common queries
class Order(models.Model):
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()

    model_options = models.Options(
        indexes=[models.Index(fields=["status", "-created_at"])],
    )
```

### Use database constraints, not app-only validation

Enforce uniqueness and data integrity at the database level.

```python
# Bad — only validated in Python
def save(self):
    if MyModel.query.filter(email=self.email).exists():
        raise ValueError("duplicate")

# Good — database-enforced
model_options = models.Options(
    constraints=[models.UniqueConstraint(fields=["email"])],
)
```

### Choose `on_delete` deliberately

CASCADE for owned children, PROTECT for referenced data, SET_NULL for optional references.

```python
# Bad — blindly using CASCADE everywhere
company = models.ForeignKey("Company", on_delete=models.CASCADE)  # deleting company deletes invoices!

# Good — protect referenced data
company = models.ForeignKey("Company", on_delete=models.PROTECT)
```

### No `allow_null` on string fields

Use `default=""` instead of `allow_null=True` to avoid two representations of "empty."

```python
# Bad — NULL and "" both mean "empty"
nickname = models.CharField(max_length=50, allow_null=True)

# Good — single empty representation
nickname = models.CharField(max_length=50, default="")
```

### HIGH — Query Efficiency

### Use `.exists()` instead of `.count() > 0`

`.exists()` stops at the first match; `.count()` scans all matching rows.

```python
# Bad
if User.query.filter(is_active=True).count() > 0:
    ...

# Good
if User.query.filter(is_active=True).exists():
    ...
```

### Use `.count()` instead of `len(queryset)`

`len()` loads all objects into memory just to count them.

```python
# Bad
total = len(User.query.all())

# Good
total = User.query.count()
```

### Use `bulk_create` / `bulk_update` for batch operations

Avoid calling `.save()` in a loop — each call is a separate query.

```python
# Bad — N INSERT statements
for name in names:
    Tag(name=name).save()

# Good — single INSERT
Tag.query.bulk_create([Tag(name=name) for name in names])
```

### Use queryset `.update()` / `.delete()` for mass operations

Execute mass changes in SQL instead of Python loops.

```python
# Bad — N UPDATE statements
for user in User.query.filter(is_active=False):
    user.is_archived = True
    user.save()

# Good — single UPDATE statement
User.query.filter(is_active=False).update(is_archived=True)
```

### Use `.only()` / `.defer()` for heavy columns

Skip large text or JSON fields when you don't need them.

```python
# Bad — loads large body text for a listing page
posts = Post.query.all()

# Good — defers heavy column
posts = Post.query.defer("body").all()
```

### Use `.iterator()` for large result sets

Process rows in chunks instead of loading everything into memory.

```python
# Bad — entire table in memory
for row in HugeTable.query.all():
    process(row)

# Good — chunked iteration
for row in HugeTable.query.iterator(chunk_size=2000):
    process(row)
```
