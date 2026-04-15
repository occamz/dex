from __future__ import annotations


class DEXError(Exception):
    """Base class for dex errors."""


class FilterError(DEXError):
    """A non-filterable expression was passed to `filter()` or `exclude()`."""


class ExpressionNotAnnotated(AttributeError):
    """An expression was accessed on an instance without being annotated first."""


class CircularDependencyError(DEXError):
    """Expression dependencies form a cycle."""
