import typing as t

from django.db import models

from dex.expression import ExpressionRef
from dex.manager import DEXManager
from dex.prefetch import PrefetchRef

T = t.TypeVar("T", bound=t.Callable)

class Model(models.Model):
    objects: DEXManager

    class Meta:
        abstract: bool

    @classmethod
    def expression(
        cls,
        output_field: models.Field,
        *,
        uses: list[ExpressionRef] | None = None,
    ) -> t.Callable[[T], ExpressionRef]: ...
    @classmethod
    def prefetch(cls) -> t.Callable[[T], PrefetchRef]: ...
