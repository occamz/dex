from __future__ import annotations

from django.db import models

from dex.manager import DEXManager


class Model(models.Model):
    """Abstract base model with `dex.Manager` set as `objects`.

    Equivalent to adding `objects = dex.Manager()` to your model:

        class BaseModel(dex.Model):
            class Meta:
                abstract = True
    """

    objects = DEXManager()

    class Meta:
        abstract = True

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        _unwrap_staticmethod_refs(cls)


def _unwrap_staticmethod_refs(cls: type[models.Model]) -> None:
    """Unwrap `@staticmethod`-wrapped refs in a model's class dict.

    Handles the inline pattern where `@staticmethod` sits above
    `@dex.expression()` or `@dex.prefetch()` for IDE compatibility.
    """
    from dex.expression import ExpressionRef
    from dex.prefetch import PrefetchRef

    if "_dex_expressions" not in cls.__dict__:
        cls._dex_expressions = {}
    if "_dex_prefetches" not in cls.__dict__:
        cls._dex_prefetches = {}

    for attr_name, value in list(cls.__dict__.items()):
        # Only plain staticmethod wrappers. ExpressionRef/PrefetchRef also
        # subclass staticmethod but are registered via contribute_to_class.
        if type(value) is not staticmethod:
            continue

        wrapped = value.__func__
        if isinstance(wrapped, ExpressionRef):
            wrapped.field_name = attr_name
            wrapped.model = cls
            cls._dex_expressions[attr_name] = wrapped
            setattr(cls, attr_name, wrapped)
        elif isinstance(wrapped, PrefetchRef):
            wrapped.name = attr_name
            wrapped.model = cls
            cls._dex_prefetches[attr_name] = wrapped
            setattr(cls, attr_name, wrapped)
