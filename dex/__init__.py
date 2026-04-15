from __future__ import annotations

import typing as t

from dex.expression import ExpressionRef, expression
from dex.prefetch import PrefetchRef, prefetch
from dex.query import query

if t.TYPE_CHECKING:
    from dex.introspection import get_expressions, get_prefetches
    from dex.manager import DEXManager as Manager
    from dex.model import Model


def __getattr__(name: str):
    """Lazy imports for Model, Manager, and introspection. Avoids Django AppRegistryNotReady."""
    if name == "Model":
        from dex.model import Model

        return Model
    if name == "Manager":
        from dex.manager import DEXManager

        return DEXManager
    if name == "get_expressions":
        from dex.introspection import get_expressions

        return get_expressions
    if name == "get_prefetches":
        from dex.introspection import get_prefetches

        return get_prefetches
    raise AttributeError(f"module 'dex' has no attribute {name!r}")


__all__ = (
    "ExpressionRef",
    "expression",
    "get_expressions",
    "get_prefetches",
    "Manager",
    "Model",
    "PrefetchRef",
    "prefetch",
    "query",
)
