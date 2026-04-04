from __future__ import annotations

from django.db import models

from dex.manager import DEXManager


class Model(models.Model):
    """
    Convenience abstract base model that sets up dex.Manager as default manager.

    Usage:
        class BaseModel(dex.Model):
            class Meta:
                abstract = True

    Equivalent to manually adding `objects = dex.Manager()` to your model.
    """

    objects = DEXManager()

    class Meta:
        abstract = True

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        _unwrap_staticmethod_refs(cls)


def _unwrap_staticmethod_refs(cls: type[models.Model]) -> None:
    """
    Detect @staticmethod-wrapped ExpressionRefs and PrefetchRefs in a model's
    class dict and unwrap them. This handles the case where @staticmethod is
    placed above @dex.expression() / @dex.prefetch() for IDE compatibility.
    """
    from dex.expression import ExpressionRef
    from dex.prefetch import PrefetchRef

    # Ensure class-local registries
    if "_dex_expressions" not in cls.__dict__:
        cls._dex_expressions = {}
    if "_dex_prefetches" not in cls.__dict__:
        cls._dex_prefetches = {}

    for attr_name, value in list(cls.__dict__.items()):
        # Only look at plain staticmethod wrappers (not ExpressionRef/PrefetchRef
        # which inherit from staticmethod but are already handled)
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
