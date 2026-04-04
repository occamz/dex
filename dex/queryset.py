from __future__ import annotations

import typing as t

if t.TYPE_CHECKING:
    from typing import Self  # noqa: F401

from django.db import models
from django.db.models import Exists, ExpressionWrapper, Q

from dex.exceptions import CircularDependencyError, FilterError
from dex.expression import BoundExpressionRef, ExpressionRef


def _apply_expression(
    qs: DEXQuerySet,
    ref: ExpressionRef | BoundExpressionRef,
    _resolving: frozenset[str] | None = None,
    _as_alias: bool = False,
) -> DEXQuerySet:
    """
    Apply a dex expression to a queryset, resolving dependencies first.

    Dependencies from `uses` are applied as aliases (not in SELECT, not on instances).
    Explicitly annotated expressions are applied as annotations.

    If an expression was previously aliased and is now explicitly annotated, it gets
    promoted from alias to annotation.
    """
    if isinstance(ref, BoundExpressionRef):
        expr_ref = ref.ref
    else:
        expr_ref = ref

    field_name = expr_ref.field_name

    # Circular dependency detection
    if _resolving is None:
        _resolving = frozenset()
    if field_name in _resolving:
        cycle = " → ".join([*_resolving, field_name])
        raise CircularDependencyError(f"Circular dependency detected: {cycle}")
    _resolving = _resolving | {field_name}

    # Apply dependencies first as aliases (left-to-right)
    for dep in expr_ref.uses or []:
        qs = _apply_expression(qs, dep, _resolving, _as_alias=True)

    annotations = getattr(qs, "_dex_annotations", set())
    aliases = getattr(qs, "_dex_aliases", set())

    # Skip if already annotated (strongest state — nothing to do)
    if field_name in annotations:
        return qs

    # Skip if already aliased AND we only need an alias
    if field_name in aliases and _as_alias:
        return qs

    # Resolve the expression
    resolved_expression = ref.resolve()

    if _as_alias:
        # Apply as alias — available to the query engine but not in SELECT
        qs = models.QuerySet.alias(qs, **{field_name: resolved_expression})
        qs._dex_aliases = aliases | {field_name}
    else:
        # Apply as annotation — in SELECT, on instances
        # This also handles promotion from alias to annotation
        qs = models.QuerySet.annotate(qs, **{field_name: resolved_expression})
        qs._dex_annotations = annotations | {field_name}
        # Remove from aliases if it was promoted
        if field_name in aliases:
            qs._dex_aliases = aliases - {field_name}

    return qs


def _is_filterable(expression: t.Any) -> bool:
    """Check if an expression can be used directly in filter/exclude."""
    if isinstance(expression, (Q, Exists)):
        return True
    if isinstance(expression, ExpressionWrapper):
        return isinstance(expression.output_field, models.BooleanField)
    return False


def _resolve_expression(ref: ExpressionRef | BoundExpressionRef) -> t.Any:
    """Resolve an ExpressionRef or BoundExpressionRef to its Django expression."""
    return ref.resolve()


def _get_expression_ref(ref: ExpressionRef | BoundExpressionRef) -> ExpressionRef:
    """Unwrap a BoundExpressionRef to get the underlying ExpressionRef."""
    if isinstance(ref, BoundExpressionRef):
        return ref.ref
    return ref


class DEXQuerySet(models.QuerySet):
    """
    Custom QuerySet that overrides annotate, filter, exclude, and prefetch_related
    to accept dex ExpressionRef and PrefetchRef objects alongside regular Django args.

    Overrides: annotate, alias, filter, exclude, prefetch_related.

    Tracks two sets of applied expressions:
    - _dex_annotations: explicitly annotated (in SELECT, on instances)
    - _dex_aliases: auto-resolved dependencies (available to query engine, not on instances)
    """

    def _chain(self, **kwargs: t.Any) -> Self:
        obj = super()._chain(**kwargs)
        obj._dex_annotations = getattr(self, "_dex_annotations", set()).copy()
        obj._dex_aliases = getattr(self, "_dex_aliases", set()).copy()
        return obj

    def annotate(self, *args: t.Any, **kwargs: t.Any) -> Self:
        """Accepts ExpressionRef/BoundExpressionRef as positional args alongside regular Django args."""
        qs = self
        regular_args = []

        for arg in args:
            if isinstance(arg, (ExpressionRef, BoundExpressionRef)):
                qs = _apply_expression(qs, arg)
            else:
                regular_args.append(arg)

        if regular_args or kwargs:
            qs = models.QuerySet.annotate(qs, *regular_args, **kwargs)
        return qs

    def alias(self, *args: t.Any, **kwargs: t.Any) -> Self:
        """Accepts ExpressionRef/BoundExpressionRef as positional args. Aliases them (not in SELECT)."""
        qs = self
        regular_args = []

        for arg in args:
            if isinstance(arg, (ExpressionRef, BoundExpressionRef)):
                qs = _apply_expression(qs, arg, _as_alias=True)
            else:
                regular_args.append(arg)

        if regular_args or kwargs:
            qs = models.QuerySet.alias(qs, *regular_args, **kwargs)
        return qs

    def filter(self, *args: t.Any, **kwargs: t.Any) -> Self:
        """Accepts Q-returning ExpressionRefs as positional args. Raises FilterError for non-filterable expressions."""
        resolved_args: list[t.Any] = []

        for arg in args:
            if isinstance(arg, (ExpressionRef, BoundExpressionRef)):
                expr_ref = _get_expression_ref(arg)
                resolved = _resolve_expression(arg)
                if not _is_filterable(resolved):
                    model_name = expr_ref.model.__name__ if expr_ref.model else "Model"
                    field_type = expr_ref.output_field.__class__.__name__
                    raise FilterError(
                        f"'{expr_ref.field_name}' returns {field_type}, not a filter condition. "
                        f"Use .annotate({model_name}.{expr_ref.field_name})"
                        f".filter({expr_ref.field_name}=...) instead."
                    )
                resolved_args.append(resolved)
            else:
                resolved_args.append(arg)

        return super().filter(*resolved_args, **kwargs)

    def exclude(self, *args: t.Any, **kwargs: t.Any) -> Self:
        """Same as filter() but excludes matching rows. Raises FilterError for non-filterable expressions."""
        resolved_args: list[t.Any] = []

        for arg in args:
            if isinstance(arg, (ExpressionRef, BoundExpressionRef)):
                expr_ref = _get_expression_ref(arg)
                resolved = _resolve_expression(arg)
                if not _is_filterable(resolved):
                    model_name = expr_ref.model.__name__ if expr_ref.model else "Model"
                    field_type = expr_ref.output_field.__class__.__name__
                    raise FilterError(
                        f"'{expr_ref.field_name}' returns {field_type}, not a filter condition. "
                        f"Use .annotate({model_name}.{expr_ref.field_name})"
                        f".exclude({expr_ref.field_name}=...) instead."
                    )
                resolved_args.append(resolved)
            else:
                resolved_args.append(arg)

        return super().exclude(*resolved_args, **kwargs)

    def prefetch_related(self, *lookups: t.Any) -> Self:
        """Accepts PrefetchRef/BoundPrefetchRef alongside regular Django Prefetch/string lookups."""
        from dex.prefetch import BoundPrefetchRef, PrefetchRef

        resolved: list[t.Any] = []
        for lookup in lookups:
            if isinstance(lookup, (PrefetchRef, BoundPrefetchRef)):
                resolved.append(lookup.resolve())
            else:
                resolved.append(lookup)
        return super().prefetch_related(*resolved)
