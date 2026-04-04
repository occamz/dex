from __future__ import annotations

import typing as t

from django.db import models

if t.TYPE_CHECKING:
    from dex.expression import ExpressionRef
    from dex.prefetch import PrefetchRef


def get_expressions(model: type[models.Model]) -> dict[str, ExpressionRef]:
    """Return all dex expressions registered on a model."""
    return dict(getattr(model, "_dex_expressions", {}))


def get_prefetches(model: type[models.Model]) -> dict[str, PrefetchRef]:
    """Return all dex prefetches registered on a model."""
    return dict(getattr(model, "_dex_prefetches", {}))
