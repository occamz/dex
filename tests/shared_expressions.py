"""
Shared expressions that can be imported into multiple models via in-class imports.
Tests the cloning behavior of contribute_to_class.
"""

from django.db import models

import dex


@dex.expression(models.BooleanField())
def is_recent():
    """Shared expression — can be imported into any model with a created_at field."""
    return models.Q(created_at__gte=models.functions.Now() - models.Value("7 days"))
