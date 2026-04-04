"""
Tests for dex expression system.

Covers: ExpressionRef descriptor, inline/external expressions, parameterized expressions,
dependency resolution, annotate/filter/exclude integration, error handling.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from django.db import models

import dex
from dex.exceptions import CircularDependencyError, ExpressionNotAnnotated, FilterError
from dex.expression import BoundExpressionRef, ExpressionRef
from tests.models import Author, Book, BookmarkV2, Review, ReviewV2

# ── Fixtures ──


@pytest.fixture
def author():
    return Author.objects.create(
        first_name="Jane",
        last_name="Austen",
        is_active=True,
    )


@pytest.fixture
def inactive_author():
    from django.utils import timezone

    return Author.objects.create(
        first_name="Ghost",
        last_name="Writer",
        is_active=False,
        deleted_at=timezone.now(),
    )


@pytest.fixture
def books(author):
    b1 = Book.objects.create(
        title="Pride and Prejudice",
        author=author,
        price=Decimal("20.00"),
        discount=Decimal("5.00"),
        published=True,
    )
    b2 = Book.objects.create(
        title="Sense and Sensibility",
        author=author,
        price=Decimal("15.00"),
        discount=Decimal("0.00"),
        published=True,
    )
    b3 = Book.objects.create(
        title="Unpublished Draft",
        author=author,
        price=Decimal("10.00"),
        discount=Decimal("0.00"),
        published=False,
    )
    return b1, b2, b3


@pytest.fixture
def reviews(books):
    b1, b2, _b3 = books
    r1 = Review.objects.create(
        book=b1, rating=5, text="Excellent!", reviewer_name="Alice", is_approved=True
    )
    r2 = Review.objects.create(
        book=b1, rating=3, text="Okay.", reviewer_name="Bob", is_approved=True
    )
    r3 = Review.objects.create(
        book=b1, rating=1, text="Spam", reviewer_name="Troll", is_approved=False
    )
    r4 = Review.objects.create(
        book=b2, rating=4, text="Great!", reviewer_name="Alice", is_approved=True
    )
    return r1, r2, r3, r4


# ── ExpressionRef Descriptor Tests ──


class TestExpressionRefDescriptor:
    def test_class_access_returns_ref(self):
        ref = Author.full_name
        assert isinstance(ref, ExpressionRef)
        assert ref.field_name == "full_name"

    def test_instance_access_raises_when_not_annotated(self, author):
        with pytest.raises(ExpressionNotAnnotated, match="full_name"):
            author.full_name

    def test_instance_access_returns_value_when_annotated(self, author):
        annotated = Author.objects.annotate(Author.full_name).get(pk=author.pk)
        assert annotated.full_name == "Jane Austen"

    def test_external_expression_accessible_on_model(self):
        ref = Author.full_name_upper
        assert isinstance(ref, ExpressionRef)
        assert ref.field_name == "full_name_upper"

    def test_expression_ref_repr(self):
        ref = Author.full_name
        assert "Author" in repr(ref)
        assert "full_name" in repr(ref)


# ── Inline Expression Tests ──


class TestInlineExpressions:
    def test_simple_annotation(self, author):
        result = Author.objects.annotate(Author.full_name).get(pk=author.pk)
        assert result.full_name == "Jane Austen"

    def test_arithmetic_annotation(self, books):
        b1, _b2, _b3 = books
        result = Book.objects.annotate(Book.discounted_price).get(pk=b1.pk)
        assert result.discounted_price == Decimal("15.00")

    def test_multiple_annotations(self, books):
        b1, _b2, _b3 = books
        result = Book.objects.annotate(Book.discounted_price, Book.is_on_sale).get(pk=b1.pk)
        assert result.discounted_price == Decimal("15.00")
        assert result.is_on_sale is True

    def test_annotation_with_regular_django_kwargs(self, books):
        b1, _b2, _b3 = books
        result = Book.objects.annotate(Book.discounted_price, custom=models.Value(42)).get(pk=b1.pk)
        assert result.discounted_price == Decimal("15.00")
        assert result.custom == 42


# ── External Expression Tests ──


class TestExternalExpressions:
    def test_external_expression_annotate(self, author):
        result = Author.objects.annotate(Author.full_name_upper).get(pk=author.pk)
        assert result.full_name_upper == "JANE AUSTEN"

    def test_external_expression_on_different_model(self, books, reviews):
        b1, _b2, _b3 = books
        result = Book.objects.annotate(Book.has_reviews).get(pk=b1.pk)
        assert result.has_reviews is True

    def test_external_expression_review_count(self, books, reviews):
        b1, _b2, b3 = books
        results = Book.objects.annotate(Book.review_count)
        b1_result = results.get(pk=b1.pk)
        b3_result = results.get(pk=b3.pk)
        assert b1_result.review_count == 3
        assert b3_result.review_count is None  # No reviews → Subquery returns None


# ── Filter/Exclude Tests ──


class TestFilterExclude:
    def test_filter_with_q_expression(self, books):
        result = Book.objects.filter(Book.is_on_sale)
        assert result.count() == 1
        assert result.first().title == "Pride and Prejudice"

    def test_filter_with_multiple_expressions(self, books):
        result = Book.objects.filter(Book.is_published, Book.is_on_sale)
        assert result.count() == 1

    def test_exclude_with_q_expression(self, books):
        result = Book.objects.exclude(Book.is_on_sale)
        assert result.count() == 2

    def test_filter_with_regular_kwargs(self, books):
        result = Book.objects.filter(Book.is_published, price__gte=Decimal("15.00"))
        assert result.count() == 2

    def test_filter_with_non_filterable_raises(self, books):
        with pytest.raises(FilterError, match="discounted_price"):
            Book.objects.filter(Book.discounted_price)

    def test_exclude_with_non_filterable_raises(self, books):
        with pytest.raises(FilterError, match="discounted_price"):
            Book.objects.exclude(Book.discounted_price)

    def test_filter_with_exists_expression(self, books, reviews):
        result = Book.objects.filter(Book.has_reviews)
        assert result.count() == 2  # b1 and b2 have reviews

    def test_filter_q_expression_for_deleted(self, author, inactive_author):
        result = Author.objects.filter(Author.is_deleted)
        assert result.count() == 1
        assert result.first().pk == inactive_author.pk

    def test_exclude_q_expression_for_deleted(self, author, inactive_author):
        result = Author.objects.exclude(Author.is_deleted)
        assert result.count() == 1
        assert result.first().pk == author.pk


# ── Parameterized Expression Tests ──


class TestParameterizedExpressions:
    def test_calling_ref_returns_bound(self):
        bound = Book.has_review_by("Alice")
        assert isinstance(bound, BoundExpressionRef)
        assert bound.field_name == "has_review_by"

    def test_parameterized_filter(self, books, reviews):
        result = Book.objects.filter(Book.has_review_by("Alice"))
        assert result.count() == 2  # b1 and b2 reviewed by Alice

    def test_parameterized_filter_no_match(self, books, reviews):
        result = Book.objects.filter(Book.has_review_by("Nobody"))
        assert result.count() == 0

    def test_parameterized_annotate(self, books, reviews):
        b1, _b2, _b3 = books
        result = Book.objects.annotate(Book.has_review_by("Alice")).get(pk=b1.pk)
        assert result.has_review_by is True

    def test_parameterized_exclude(self, books, reviews):
        result = Book.objects.exclude(Book.has_review_by("Alice"))
        # b3 has no reviews at all → not reviewed by Alice → included in exclude
        assert result.count() == 1
        assert result.first().title == "Unpublished Draft"


# ── Dependency Resolution Tests ──


class TestDependencyResolution:
    def test_uses_auto_resolves_as_alias(self, books):
        b1, _b2, _b3 = books
        # discounted_price_display depends on discounted_price
        result = Book.objects.annotate(Book.discounted_price_display).get(pk=b1.pk)
        assert result.discounted_price_display == Decimal("15.00")
        # The dependency should be aliased, NOT annotated — not accessible on instance
        with pytest.raises(ExpressionNotAnnotated):
            result.discounted_price

    def test_explicit_annotation_promotes_alias(self, books):
        b1, _b2, _b3 = books
        # Annotate discounted_price explicitly AND discounted_price_display
        # discounted_price is both an explicit annotation and a dependency — annotation wins
        result = Book.objects.annotate(Book.discounted_price, Book.discounted_price_display).get(
            pk=b1.pk
        )
        assert result.discounted_price == Decimal("15.00")
        assert result.discounted_price_display == Decimal("15.00")

    def test_aliased_deps_usable_in_filter(self, books):
        # discounted_price_display uses discounted_price as a dep (aliased)
        # The alias should still be usable for the annotation's filter
        qs = Book.objects.annotate(Book.discounted_price_display).filter(
            discounted_price_display__lt=12
        )
        assert qs.count() == 1  # Only the 10.00 book

    def test_aliased_deps_usable_in_order_by(self, books):
        qs = Book.objects.annotate(Book.discounted_price_display).order_by(
            "discounted_price_display"
        )
        prices = list(qs.values_list("discounted_price_display", flat=True))
        assert prices == sorted(prices)


class TestCircularDependency:
    def test_circular_dependency_detected(self):
        """Create two expressions that depend on each other and verify detection."""
        ref_a = ExpressionRef(
            field_name="a",
            output_field=models.IntegerField(),
            expression_fn=lambda: models.Value(1),
            uses=[],
        )
        ref_b = ExpressionRef(
            field_name="b",
            output_field=models.IntegerField(),
            expression_fn=lambda: models.Value(2),
            uses=[ref_a],
        )
        # Create the cycle
        ref_a.uses = [ref_b]

        with pytest.raises(CircularDependencyError):
            Book.objects.annotate(ref_a)


# ── Alias Tests ──


class TestAlias:
    def test_alias_with_expression_ref(self, books):
        """alias() accepts ExpressionRefs — field is NOT on instances but usable in filter."""
        qs = Book.objects.alias(Book.discounted_price).filter(discounted_price__lt=12)
        assert qs.count() == 1  # Only the 10.00 book

    def test_alias_not_on_instance(self, books):
        """Aliased expressions are not accessible on model instances."""
        result = Book.objects.alias(Book.discounted_price).filter(discounted_price__lt=20).first()
        with pytest.raises(ExpressionNotAnnotated):
            result.discounted_price

    def test_alias_usable_in_order_by(self, books):
        qs = Book.objects.alias(Book.discounted_price).order_by("discounted_price")
        titles = list(qs.values_list("title", flat=True))
        assert titles[0] == "Unpublished Draft"  # 10.00, cheapest

    def test_alias_with_regular_kwargs(self, books):
        """alias() still accepts regular Django kwargs alongside dex refs."""
        qs = Book.objects.alias(Book.discounted_price, custom=models.Value(1)).filter(
            discounted_price__lt=12
        )
        assert qs.count() == 1

    def test_alias_resolves_deps_as_aliases(self, books):
        """Dependencies of an aliased expression are also aliased."""
        qs = Book.objects.alias(Book.discounted_price_display).filter(
            discounted_price_display__gt=0
        )
        assert qs.count() == 3
        # Neither the dep nor the expression itself should be on instances
        result = qs.first()
        with pytest.raises(ExpressionNotAnnotated):
            result.discounted_price
        with pytest.raises(ExpressionNotAnnotated):
            result.discounted_price_display


# ── Queryset Chaining Tests ──


class TestQuerysetChaining:
    def test_annotations_persist_through_filter(self, books):
        qs = Book.objects.annotate(Book.discounted_price).filter(discounted_price__lt=20)
        assert qs.count() == 3  # All books have discounted_price < 20

    def test_annotations_persist_through_order_by(self, books):
        qs = Book.objects.annotate(Book.discounted_price).order_by("discounted_price")
        prices = list(qs.values_list("discounted_price", flat=True))
        assert prices == sorted(prices)

    def test_annotations_persist_through_exclude(self, books):
        qs = Book.objects.annotate(Book.discounted_price).exclude(discounted_price__gt=100)
        assert qs.count() == 3

    def test_dex_annotations_tracked_through_chain(self, books):
        qs = Book.objects.annotate(Book.discounted_price)
        qs2 = qs.filter(price__gt=0)
        assert "discounted_price" in getattr(qs2, "_dex_annotations", set())

    def test_mixed_dex_and_django_annotations(self, books):
        b1, _b2, _b3 = books
        result = Book.objects.annotate(
            Book.discounted_price, margin=models.F("price") - models.F("discount")
        ).get(pk=b1.pk)
        assert result.discounted_price == Decimal("15.00")
        assert result.margin == Decimal("15.00")


# ── Prefetch Tests ──


class TestPrefetch:
    def test_inline_prefetch(self, books, reviews):
        b1, _b2, _b3 = books
        result = Book.objects.prefetch_related(Book.reviews_prefetch).get(pk=b1.pk)
        assert hasattr(result, "approved_reviews")
        assert len(result.approved_reviews) == 2  # 2 approved out of 3

    def test_parameterized_prefetch(self, books, reviews):
        b1, _b2, _b3 = books
        result = Book.objects.prefetch_related(Book.reviews_by_rating(4)).get(pk=b1.pk)
        assert hasattr(result, "filtered_reviews")
        assert all(r.rating >= 4 for r in result.filtered_reviews)

    def test_prefetch_with_annotations(self, books, reviews):
        b1, _b2, _b3 = books
        result = (
            Book.objects.annotate(Book.discounted_price)
            .prefetch_related(Book.reviews_prefetch)
            .get(pk=b1.pk)
        )
        assert result.discounted_price == Decimal("15.00")
        assert len(result.approved_reviews) == 2


# ── Introspection Tests ──


class TestIntrospection:
    def test_get_expressions_returns_all(self):
        expressions = dex.get_expressions(Book)
        assert "discounted_price" in expressions
        assert "is_on_sale" in expressions
        assert "has_reviews" in expressions
        assert "review_count" in expressions
        assert "has_review_by" in expressions
        assert "discounted_price_display" in expressions

    def test_get_prefetches_returns_all(self):
        prefetches = dex.get_prefetches(Book)
        assert "reviews_prefetch" in prefetches
        assert "reviews_by_rating" in prefetches

    def test_get_expressions_empty_model(self):
        expressions = dex.get_expressions(Review)
        assert expressions == {}

    def test_get_prefetches_empty_model(self):
        prefetches = dex.get_prefetches(Author)
        assert prefetches == {}


# ── Query (Layer 2) Tests ──


class TestQuery:
    def test_query_decorator(self, books):
        @dex.query(Book)
        def cheap_books(qs):
            return qs.annotate(Book.discounted_price).filter(discounted_price__lt=11)

        result = cheap_books(Book.objects.all())
        assert result.count() == 1  # Only the 10.00 book

    def test_query_default_queryset(self, books):
        @dex.query(Book)
        def all_with_price(qs):
            return qs.annotate(Book.discounted_price)

        result = all_with_price()
        assert result.count() == 3

    def test_query_with_parameters(self, books):
        @dex.query(Book)
        def books_under(qs, max_price):
            return qs.annotate(Book.discounted_price).filter(discounted_price__lt=max_price)

        result = books_under(Book.objects.all(), max_price=Decimal("12.00"))
        assert result.count() == 1  # Only the 10.00 book

    def test_query_composable(self, books, reviews):
        @dex.query(Book)
        def with_prices(qs):
            return qs.annotate(Book.discounted_price)

        @dex.query(Book)
        def with_review_info(qs):
            return qs.annotate(Book.review_count)

        qs = Book.objects.all()
        qs = with_prices(qs)
        qs = with_review_info(qs)
        b1 = qs.get(title="Pride and Prejudice")
        assert b1.discounted_price == Decimal("15.00")
        assert b1.review_count == 3


# ── In-class Import Tests ──


class TestInClassImports:
    def test_in_class_import_expression_accessible(self):
        """Expression imported via `from ... import` inside class body is on the model."""
        ref = ReviewV2.is_recent
        assert isinstance(ref, ExpressionRef)
        assert ref.field_name == "is_recent"
        assert ref.model is ReviewV2

    def test_in_class_import_cloned_per_model(self):
        """Same expression imported into two models gets cloned — not shared."""
        review_ref = ReviewV2.is_recent
        bookmark_ref = BookmarkV2.is_recent
        assert review_ref is not bookmark_ref
        assert review_ref.model is ReviewV2
        assert bookmark_ref.model is BookmarkV2
        assert review_ref.field_name == "is_recent"
        assert bookmark_ref.field_name == "is_recent"

    def test_in_class_import_registered(self):
        """In-class imported expression is in the model's dex registry."""
        assert "is_recent" in dex.get_expressions(ReviewV2)
        assert "is_recent" in dex.get_expressions(BookmarkV2)
