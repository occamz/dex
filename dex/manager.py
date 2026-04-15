from __future__ import annotations

from django.db import models
from django.db.models.manager import BaseManager

from dex.expression import _make_model_expression_classmethod
from dex.prefetch import _make_model_prefetch_classmethod
from dex.queryset import DEXQuerySet


class DEXManager(BaseManager.from_queryset(DEXQuerySet)):
    """Django model manager that enables dex expressions and prefetches.

    On `contribute_to_class`, attaches `.expression()` and `.prefetch()`
    classmethods and initializes the per-class registries, merging any
    parent refs from the MRO.
    """

    def contribute_to_class(self, cls: type[models.Model], name: str) -> None:
        super().contribute_to_class(cls, name)

        if "expression" not in cls.__dict__:
            cls.expression = _make_model_expression_classmethod()

        if "prefetch" not in cls.__dict__:
            cls.prefetch = _make_model_prefetch_classmethod()

        # Class-local registries. Inline refs may have created these already
        # via contribute_to_class, which runs before the manager's.
        if "_dex_expressions" not in cls.__dict__:
            cls._dex_expressions = {}
        if "_dex_prefetches" not in cls.__dict__:
            cls._dex_prefetches = {}

        # Inherit parent refs that this class hasn't overridden.
        for parent in cls.__mro__[1:]:
            for key, ref in parent.__dict__.get("_dex_expressions", {}).items():
                cls._dex_expressions.setdefault(key, ref)
            for key, ref in parent.__dict__.get("_dex_prefetches", {}).items():
                cls._dex_prefetches.setdefault(key, ref)
