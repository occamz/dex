import contextlib

import pytest
from django.db import connection


def pytest_configure(config):
    """Register the dex test models with Django."""
    from django.conf import settings

    if "tests" not in settings.INSTALLED_APPS:
        settings.INSTALLED_APPS = [*settings.INSTALLED_APPS, "tests"]


@pytest.fixture(scope="session")
def dex_tables(django_db_setup, django_db_blocker):
    """Create dex test tables once per test session."""
    from tests.models import Author, Book, BookmarkV2, Review, ReviewV2

    all_models = (Author, Book, Review, ReviewV2, BookmarkV2)

    with django_db_blocker.unblock():
        for model in all_models:
            with contextlib.suppress(Exception):
                with connection.schema_editor() as schema_editor:
                    schema_editor.create_model(model)

    yield

    with django_db_blocker.unblock():
        for model in reversed(all_models):
            with contextlib.suppress(Exception):
                with connection.schema_editor() as schema_editor:
                    schema_editor.delete_model(model)


@pytest.fixture(autouse=True)
def _dex_db(dex_tables, db):
    """Ensure dex tables exist and DB access is enabled for all dex tests."""
