"""
Test models for dex.

These models are only used in tests. They are registered via the dex.tests app
and created in the test database using --nomigrations (or a test migration).
"""

from __future__ import annotations

from django.db import models

import dex


class Author(dex.Model):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    @staticmethod
    @dex.expression(models.CharField())
    def full_name():
        return models.functions.Concat(
            models.F("first_name"), models.Value(" "), models.F("last_name")
        )

    @staticmethod
    @dex.expression(models.BooleanField())
    def is_deleted():
        return models.Q(deleted_at__isnull=False)

    class Meta:
        app_label = "dex_tests"


class Book(dex.Model):
    title = models.CharField(max_length=200)
    author = models.ForeignKey(Author, on_delete=models.CASCADE, related_name="books")
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    published = models.BooleanField(default=False)

    @staticmethod
    @dex.expression(models.DecimalField())
    def discounted_price():
        return models.F("price") - models.F("discount")

    @staticmethod
    @dex.expression(models.BooleanField())
    def is_on_sale():
        return models.Q(discount__gt=0)

    @staticmethod
    @dex.expression(models.BooleanField())
    def is_published():
        return models.Q(published=True)

    @staticmethod
    @dex.prefetch()
    def reviews_prefetch():
        return models.Prefetch(
            "reviews",
            queryset=Review.objects.filter(is_approved=True).order_by("-created_at"),
            to_attr="approved_reviews",
        )

    class Meta:
        app_label = "dex_tests"


class Review(dex.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reviews")
    rating = models.IntegerField()
    text = models.TextField()
    reviewer_name = models.CharField(max_length=100)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "dex_tests"


# ── In-class imports (the recommended pattern for external expressions) ──
# These simulate `from db.expressions.x import y` inside a class body.
# The same expression can be imported into multiple models — cloned automatically.


class ReviewV2(dex.Model):
    """A model that uses in-class imports for expressions."""

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="reviews_v2")
    rating = models.IntegerField()
    reviewer_name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    # In-class import — expression defined elsewhere, IDE resolves it
    from tests.shared_expressions import is_recent

    class Meta:
        app_label = "dex_tests"


class BookmarkV2(dex.Model):
    """Another model importing the same shared expression — tests cloning."""

    user_name = models.CharField(max_length=100)
    url = models.URLField()
    created_at = models.DateTimeField(auto_now_add=True)

    # Same expression, different model — should be cloned
    from tests.shared_expressions import is_recent

    class Meta:
        app_label = "dex_tests"


# ── External expressions (simulating what would be in separate files) ──


@Author.expression(models.CharField())
def full_name_upper():
    return models.functions.Upper(
        models.functions.Concat(models.F("first_name"), models.Value(" "), models.F("last_name"))
    )


@Book.expression(models.BooleanField())
def has_reviews():
    return models.Exists(Review.objects.filter(book_id=models.OuterRef("id")))


@Book.expression(models.IntegerField())
def review_count():
    return models.Subquery(
        Review.objects.filter(book_id=models.OuterRef("id"))
        .values("book_id")
        .annotate(count=models.Count("id"))
        .values("count")
    )


# ── Expression with dependencies (uses) ──


@Book.expression(
    models.DecimalField(),
    uses=[Book.discounted_price],
)
def discounted_price_display():
    """Depends on discounted_price being annotated first."""
    return models.F("discounted_price") * models.Value(1)


# ── Parameterized expression ──


@Book.expression(models.BooleanField())
def has_review_by(reviewer_name):
    return models.Exists(
        Review.objects.filter(
            book_id=models.OuterRef("id"),
            reviewer_name=reviewer_name,
        )
    )


# ── Parameterized prefetch ──


@Book.prefetch()
def reviews_by_rating(min_rating=1):
    return models.Prefetch(
        "reviews",
        queryset=Review.objects.filter(rating__gte=min_rating).order_by("-rating"),
        to_attr="filtered_reviews",
    )
