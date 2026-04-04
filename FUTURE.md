# dex — Future Roadmap

Features that are designed but not yet implemented. The current API is designed
to support these additions without breaking changes.

## Unused Annotation Warnings

Detect annotated expressions that are never accessed on instances. Dev-mode only.

```python
# settings.py
DEX = {
    "WARN_UNUSED": DEBUG,
}
```

**Implementation approach:**
- Track which dex annotations are applied in `_dex_annotations`
- Track which are accessed via the descriptor's `__get__`
- On queryset garbage collection (or via middleware), compare the sets
- Log a warning for annotations that were applied but never accessed

## Materialized Views

Precompute and cache `@dex.query` results in a managed shadow table.

```python
# Future API:
recipe_card.refresh()                                          # Recompute all
recipe_card.refresh(Recipe.objects.filter(is_published=True))  # Recompute subset
recipe_card.from_cache(Recipe.objects.filter(is_published=True))  # Read from cache
```

**Design considerations:**
- `@dex.query` already stores the model reference — this provides the identity
- The shadow table schema would be auto-generated from the query's annotations
- `refresh()` evaluates the query and writes results to the shadow table
- `from_cache()` reads from the shadow table with the same filters
- No scheduling — the project wires refresh into its own pipeline (management command, task queue, etc.)
- Parameterized queries: each parameter combination could be a separate cache key, or caching could be limited to non-parameterized queries

## Static Analysis Plugin

A mypy/pyright plugin that:
- Tracks `.annotate(Model.ref)` calls on querysets
- Flags `instance.ref` access when ref wasn't in a preceding `.annotate()`
- Flags annotated refs that are never accessed downstream
- Understands `uses` dependency chains

## CI Unused Detection

A test helper or management command that runs the unused detection logic across
a test suite and reports wasteful annotations. Could run as a pytest plugin.
