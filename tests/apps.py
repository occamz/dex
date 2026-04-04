from django.apps import AppConfig


class DEXTestsConfig(AppConfig):
    name = "tests"
    label = "dex_tests"
    verbose_name = "DEX Tests"
    default_auto_field = "django.db.models.BigAutoField"
