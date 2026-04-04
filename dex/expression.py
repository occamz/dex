from __future__ import annotations

import typing as t

from django.db import models

from dex.exceptions import ExpressionNotAnnotated


class ExpressionRef(staticmethod):
    """
    A named, reusable ORM expression bound to a Django model.

    Inherits from staticmethod so that PyCharm recognizes decorated functions
    inside class bodies don't need a `self` parameter.

    Acts as a descriptor on the model class:
    - Class access (Model.ref) returns the ExpressionRef itself (for use in queryset methods)
    - Instance access (instance.ref) returns the annotated value, or raises if not annotated

    Can be called with arguments for parameterized expressions:
        Model.is_read(user) → BoundExpressionRef
    """

    def __init__(
        self,
        field_name: str,
        output_field: models.Field,
        expression_fn: t.Callable,
        uses: list[ExpressionRef] | None = None,
        model: type[models.Model] | None = None,
    ):
        super().__init__(expression_fn)
        self.field_name = field_name
        self.output_field = output_field
        self.expression_fn = expression_fn
        self.uses: list[ExpressionRef] = uses or []
        self.model = model

    def __repr__(self) -> str:
        model_name = self.model.__name__ if self.model else "?"
        return f"dex.ExpressionRef({model_name}.{self.field_name})"

    def __get__(self, obj: t.Any, objtype: type | None = None) -> t.Any:
        if obj is None:
            return self

        # Instance access — return the annotated value
        if self.field_name in obj.__dict__:
            return obj.__dict__[self.field_name]

        raise ExpressionNotAnnotated(
            f"'{self.field_name}' is a dex expression on {objtype.__name__}. "
            f"Call .annotate({objtype.__name__}.{self.field_name}) on the queryset first."
        )

    def __call__(self, *args: t.Any, **kwargs: t.Any) -> BoundExpressionRef:
        return BoundExpressionRef(self, args, kwargs)

    def _clone(self, field_name: str, model: type[models.Model]) -> ExpressionRef:
        """Create a copy bound to a specific model."""
        return ExpressionRef(
            field_name=field_name,
            output_field=self.output_field,
            expression_fn=self.expression_fn,
            uses=list(self.uses),
            model=model,
        )

    def contribute_to_class(self, cls: type[models.Model], name: str) -> None:
        """Called by Django's ModelBase metaclass for inline and in-class-imported expressions."""
        # Clone so the same ExpressionRef can be imported into multiple models
        # without them sharing mutable state (model, field_name)
        ref = self._clone(field_name=name, model=cls)
        # Always ensure a class-local dict (don't mutate parent's)
        if "_dex_expressions" not in cls.__dict__:
            cls._dex_expressions = {}
        cls._dex_expressions[name] = ref
        setattr(cls, name, ref)

    def resolve(self) -> t.Any:
        """Evaluate the expression function (no arguments)."""
        return self.expression_fn()


class BoundExpressionRef:
    """An ExpressionRef with bound arguments for parameterized expressions."""

    def __init__(
        self,
        ref: ExpressionRef,
        args: tuple[t.Any, ...],
        kwargs: dict[str, t.Any],
    ):
        self.ref = ref
        self.args = args
        self.kwargs = kwargs

    def __repr__(self) -> str:
        return f"dex.BoundExpressionRef({self.ref!r}, args={self.args})"

    @property
    def field_name(self) -> str:
        return self.ref.field_name

    @property
    def output_field(self) -> models.Field:
        return self.ref.output_field

    @property
    def uses(self) -> list[ExpressionRef]:
        return self.ref.uses

    @property
    def model(self) -> type[models.Model] | None:
        return self.ref.model

    def resolve(self) -> t.Any:
        """Evaluate the expression function with bound arguments."""
        return self.ref.expression_fn(*self.args, **self.kwargs)


def _unwrap_function(fn: t.Any) -> t.Callable:
    """
    Unwrap @staticmethod or ExpressionRef if present, returning the raw callable.
    Handles cases where an already-decorated ExpressionRef is passed to @Model.expression().
    """
    if isinstance(fn, staticmethod):
        return fn.__func__
    if isinstance(fn, ExpressionRef):
        return fn.expression_fn
    return fn


def expression(
    output_field: models.Field,
    *,
    uses: list[ExpressionRef] | None = None,
) -> t.Callable[[t.Callable], ExpressionRef]:
    """
    Decorator for defining named expressions on a model.

    Inline usage:
        class User(dex.Model):
            @staticmethod
            @dex.expression(models.CharField())
            def full_name():
                return Concat(F("first_name"), Value(" "), F("last_name"))

    The @staticmethod is recommended for inline expressions to suppress IDE warnings.
    It is automatically unwrapped by dex.

    The returned ExpressionRef has contribute_to_class, so Django's ModelBase
    metaclass will pick it up and register it on the model.
    """

    def decorator(fn: t.Callable) -> ExpressionRef:
        fn = _unwrap_function(fn)
        return ExpressionRef(
            field_name=fn.__name__,
            output_field=output_field,
            expression_fn=fn,
            uses=uses or [],
        )

    return decorator


def _make_model_expression_classmethod() -> classmethod:
    """
    Creates the .expression() classmethod that gets attached to models by the Manager.

    Usage (external, in a separate file):
        @User.expression(models.CharField())
        def full_name():
            return Concat(F("first_name"), Value(" "), F("last_name"))
    """

    def model_expression(
        cls,
        output_field: models.Field,
        *,
        uses: list[ExpressionRef] | None = None,
    ) -> t.Callable:
        def decorator(fn: t.Callable) -> ExpressionRef:
            ref = ExpressionRef(
                field_name=fn.__name__,
                output_field=output_field,
                expression_fn=fn,
                uses=uses or [],
                model=cls,
            )
            setattr(cls, fn.__name__, ref)
            if not hasattr(cls, "_dex_expressions"):
                cls._dex_expressions = {}
            cls._dex_expressions[fn.__name__] = ref
            return ref

        return decorator

    return classmethod(model_expression)
