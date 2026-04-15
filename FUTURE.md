# dex - future roadmap

Planned features. The current API supports these additions without breaking changes.

## Unused Annotation Warnings

Detect annotated expressions that are never accessed on instances. Dev-mode only.

```python
# settings.py
DEX = {
    "WARN_UNUSED": DEBUG,
}
```

Implementation approach:

- Track applied annotations in `_dex_annotations`.
- Track accesses via the descriptor's `__get__`.
- On queryset garbage collection (or via middleware), compare the sets.
- Log a warning for annotations that were applied but never accessed.

## Materialized Views

Precompute and cache `@dex.query` results in a managed shadow table.

```python
# Future API:
recipe_card.refresh()                                             # Recompute all
recipe_card.refresh(Recipe.objects.filter(is_published=True))     # Recompute subset
recipe_card.from_cache(Recipe.objects.filter(is_published=True))  # Read from cache
```

Design notes:

- `@dex.query` already stores the model reference, which gives it an identity.
- The shadow table schema would be auto-generated from the query's annotations.
- `refresh()` evaluates the query and writes results to the shadow table.
- `from_cache()` reads from the shadow table with the same filters.
- No built-in scheduling. Projects wire refresh into their own pipeline (management command, task queue, etc.).
- Parameterized queries would either key the cache by parameter combination, or be excluded from caching.

## Static Analysis Plugin

A mypy/pyright plugin that:

- Tracks `.annotate(Model.ref)` calls on querysets.
- Flags `instance.ref` access when `ref` wasn't in a preceding `.annotate()`.
- Flags annotated refs that are never accessed downstream.
- Understands `uses` dependency chains.

## CI Unused Detection

A test helper or management command that runs the unused detection logic across a test suite and reports wasteful annotations. Could run as a pytest plugin.
