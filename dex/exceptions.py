from __future__ import annotations


class DEXError(Exception):
    """Base exception for dex."""


class FilterError(DEXError):
    """Raised when a non-filterable expression is used in filter/exclude."""


class ExpressionNotAnnotated(AttributeError):
    """Raised when accessing a dex expression that wasn't annotated on the queryset."""


class CircularDependencyError(DEXError):
    """Raised when expression dependencies form a cycle."""
