from __future__ import annotations

import importlib

from django.apps import AppConfig


class DEXConfig(AppConfig):
    name = "dex"
    verbose_name = "Django Expressions"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from django.conf import settings

        dex_settings = getattr(settings, "DEX", {})
        for module in dex_settings.get("MODULES", []):
            importlib.import_module(module)
