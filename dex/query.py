from __future__ import annotations

import functools
import typing as t

from django.db import models


class QueryWrapper:
    """
    Wraps a composed query function with model identity and future materialization hooks.

    The wrapped function takes a queryset as its first argument and returns a queryset.
    If called without a queryset, it defaults to Model.objects.all().
    """

    def __init__(self, fn: t.Callable, model: type[models.Model]):
        self.fn = fn
        self.model = model

    def __call__(
        self, qs: models.QuerySet | None = None, *args: t.Any, **kwargs: t.Any
    ) -> models.QuerySet:
        if qs is None:
            qs = self.model.objects.all()
        return self.fn(qs, *args, **kwargs)

    def __repr__(self) -> str:
        return f"dex.query({self.model.__name__}).{self.fn.__name__}"


def query(model: type[models.Model]) -> t.Callable:
    """
    Decorator for defining composed queries (Layer 2).

    Usage:
        @dex.query(Recipe)
        def recipe_card(qs):
            return qs.annotate(Recipe.total_time, Recipe.avg_rating)

        # Call it:
        recipe_card(Recipe.objects.filter(is_published=True)).order_by(...)
    """

    def decorator(fn: t.Callable) -> QueryWrapper:
        wrapper = QueryWrapper(fn, model)
        functools.update_wrapper(wrapper, fn)
        return wrapper

    return decorator
