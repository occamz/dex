from __future__ import annotations

from django.db import models
from django.db.models.manager import BaseManager

from dex.expression import _make_model_expression_classmethod
from dex.prefetch import _make_model_prefetch_classmethod
from dex.queryset import DEXQuerySet


class DEXManager(BaseManager.from_queryset(DEXQuerySet)):
    """
    Django model manager that enables dex expressions and prefetches.

    On contribute_to_class, adds .expression() and .prefetch() classmethods
    to the model, and initializes the expression/prefetch registries.
    """

    def contribute_to_class(self, cls: type[models.Model], name: str) -> None:
        super().contribute_to_class(cls, name)

        # Add .expression() classmethod if not already present on this class
        if "expression" not in cls.__dict__:
            cls.expression = _make_model_expression_classmethod()

        # Add .prefetch() classmethod if not already present on this class
        if "prefetch" not in cls.__dict__:
            cls.prefetch = _make_model_prefetch_classmethod()

        # Ensure class-local registries (inline expressions may have already created these
        # via ExpressionRef.contribute_to_class, which runs before the manager)
        if "_dex_expressions" not in cls.__dict__:
            cls._dex_expressions = {}
        if "_dex_prefetches" not in cls.__dict__:
            cls._dex_prefetches = {}

        # Merge parent expressions/prefetches (inheritance support)
        # Walk the MRO and copy parent-defined refs that aren't overridden by this class
        for parent in cls.__mro__[1:]:
            for key, ref in parent.__dict__.get("_dex_expressions", {}).items():
                cls._dex_expressions.setdefault(key, ref)
            for key, ref in parent.__dict__.get("_dex_prefetches", {}).items():
                cls._dex_prefetches.setdefault(key, ref)
