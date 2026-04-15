from __future__ import annotations

import typing as t

from django.db import models


class PrefetchRef(staticmethod):
    """A named prefetch recipe bound to a Django model.

    Subclasses staticmethod so PyCharm doesn't flag `self`-less functions
    in class bodies. Acts as a descriptor: class access returns the ref.
    Prefetched data lives in Django's `_prefetched_objects_cache`, so
    instance access isn't meaningful here.

    Call it with arguments for parameterized prefetches:
        Model.assets("reply_to")  ->  BoundPrefetchRef
    """

    def __init__(
        self,
        name: str,
        prefetch_fn: t.Callable,
        model: type[models.Model] | None = None,
    ):
        super().__init__(prefetch_fn)
        self.name = name
        self.prefetch_fn = prefetch_fn
        self.model = model

    def __repr__(self) -> str:
        model_name = self.model.__name__ if self.model else "?"
        return f"dex.PrefetchRef({model_name}.{self.name})"

    def __get__(self, obj: t.Any, objtype: type | None = None) -> t.Any:
        if obj is None:
            return self
        # Instance access: Django normally populates prefetched attrs via
        # _prefetched_objects_cache. If that hasn't happened, raise so the
        # user knows to call .prefetch_related() on the queryset.
        raise AttributeError(
            f"'{objtype.__name__}' object has no attribute '{self.name}'. "
            f"If this is a dex prefetch, call "
            f".prefetch_related({objtype.__name__}.{self.name}) on the queryset."
        )

    def __call__(self, *args: t.Any, **kwargs: t.Any) -> BoundPrefetchRef:
        return BoundPrefetchRef(self, args, kwargs)

    def _clone(self, name: str, model: type[models.Model]) -> PrefetchRef:
        """Return a copy bound to a specific model."""
        return PrefetchRef(
            name=name,
            prefetch_fn=self.prefetch_fn,
            model=model,
        )

    def contribute_to_class(self, cls: type[models.Model], name: str) -> None:
        """Register on the model. Called by Django's ModelBase metaclass."""
        # Clone so the same PrefetchRef can be imported into multiple models.
        ref = self._clone(name=name, model=cls)
        if "_dex_prefetches" not in cls.__dict__:
            cls._dex_prefetches = {}
        cls._dex_prefetches[name] = ref
        setattr(cls, name, ref)

    def resolve(self) -> t.Any:
        """Evaluate the function with no arguments. Returns a `Prefetch`."""
        return self.prefetch_fn()


class BoundPrefetchRef:
    """A `PrefetchRef` with bound call arguments (parameterized prefetches)."""

    def __init__(
        self,
        ref: PrefetchRef,
        args: tuple[t.Any, ...],
        kwargs: dict[str, t.Any],
    ):
        self.ref = ref
        self.args = args
        self.kwargs = kwargs

    def __repr__(self) -> str:
        return f"dex.BoundPrefetchRef({self.ref!r}, args={self.args})"

    @property
    def name(self) -> str:
        return self.ref.name

    @property
    def model(self) -> type[models.Model] | None:
        return self.ref.model

    def resolve(self) -> t.Any:
        """Evaluate the prefetch function with the bound arguments."""
        return self.ref.prefetch_fn(*self.args, **self.kwargs)


def _unwrap_function(fn: t.Any) -> t.Callable:
    """Return the raw callable from a `@staticmethod` or `PrefetchRef` wrapper."""
    if isinstance(fn, staticmethod):
        return fn.__func__
    if isinstance(fn, PrefetchRef):
        return fn.prefetch_fn
    return fn


def prefetch() -> t.Callable[[t.Callable], PrefetchRef]:
    """Decorator that turns a function into a named model prefetch.

    Inline usage:
        class ContentItem(dex.Model):
            @dex.prefetch()
            def assets():
                return Prefetch("item_assets", queryset=...)
    """

    def decorator(fn: t.Callable) -> PrefetchRef:
        fn = _unwrap_function(fn)
        return PrefetchRef(
            name=fn.__name__,
            prefetch_fn=fn,
        )

    return decorator


def _make_model_prefetch_classmethod() -> classmethod:
    """Build the `.prefetch()` classmethod attached to models by the Manager.

    Enables external, out-of-class registration:
        @ContentItem.prefetch()
        def assets():
            return Prefetch("item_assets", queryset=...)
    """

    def model_prefetch(cls) -> t.Callable:
        def decorator(fn: t.Callable) -> PrefetchRef:
            ref = PrefetchRef(
                name=fn.__name__,
                prefetch_fn=fn,
                model=cls,
            )
            setattr(cls, fn.__name__, ref)
            if not hasattr(cls, "_dex_prefetches"):
                cls._dex_prefetches = {}
            cls._dex_prefetches[fn.__name__] = ref
            return ref

        return decorator

    return classmethod(model_prefetch)
