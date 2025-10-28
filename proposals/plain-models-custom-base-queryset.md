# plain-models: Custom Base QuerySet

- Add `default_queryset()` classmethod to QuerySet that subclasses can override
- Replaces functionality lost in Manager/QuerySet merge (commit `bbaee93839`)
- Common use cases: soft deletes, multi-tenancy, published content, archived records
- More flexible than filters-only (can use `.select_related()`, `.only()`, etc.)
- Must preserve `base_queryset` for framework operations (migrations, cascades)
- Need some way to bypass defaults when needed (naming/approach TBD)
- Usage example:

    ```python
    class SoftDeleteQuerySet(QuerySet["Article"]):
        @classmethod
        def default_queryset(cls, model):
            return super().default_queryset(model).filter(deleted_at__isnull=True)

        def with_deleted(self):
            # How to get unfiltered queryset? TBD
            pass

    class Article(Model):
        query = SoftDeleteQuerySet()
    ```

- Implementation details TBD (how to integrate with `from_model()`, avoid duplication, bypass mechanism, etc.)
