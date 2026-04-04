# dex — Django Expressions

dex lets you define named, reusable ORM expressions and prefetches on Django models.
They plug into standard Django queryset methods — no new query API to learn.

See README.md for full documentation. This file covers conventions for working with dex.

## Quick Reference

```python
import dex
from django.db import models

# Define (external file):
@dex.expression(models.IntegerField())
def total_time():
    return models.F("prep_minutes") + models.F("cook_minutes")

# Bind to model (in-class import):
class Recipe(dex.Model):
    from myapp.expressions.recipe import total_time, avg_rating, is_vegetarian

# Use (standard Django methods):
Recipe.objects.annotate(Recipe.total_time).filter(total_time__lte=30)
Recipe.objects.alias(Recipe.avg_rating).filter(avg_rating__gte=4)
Recipe.objects.filter(Recipe.is_vegetarian)
Recipe.objects.prefetch_related(Recipe.top_reviews)
```

## Defining Expressions

### Inline (inside a class body)

`@staticmethod` must go ABOVE `@dex.expression()` to suppress IDE warnings:

```python
class Recipe(dex.Model):
    @staticmethod
    @dex.expression(models.BooleanField())
    def is_quick():
        return models.Q(prep_minutes__lte=10, cook_minutes__lte=20)
```

### External with in-class import (recommended)

Define in a separate file, import into the model class body:

```python
# expressions/recipe.py — no @staticmethod needed
@dex.expression(models.BooleanField())
def is_vegetarian():
    from myapp.models import RecipeIngredient
    return ~models.Exists(
        RecipeIngredient.objects.filter(recipe_id=models.OuterRef("id"), ingredient__category="meat")
    )

# models/recipe.py
class Recipe(dex.Model):
    from myapp.expressions.recipe import is_vegetarian
```

Use local imports inside expression bodies to avoid circular imports.

## Dependencies

`uses` declares dependencies. They're applied as aliases (not on instances):

```python
@dex.expression(models.DecimalField())
def avg_rating():
    return models.Subquery(...)

@dex.expression(models.BooleanField(), uses=[avg_rating, review_count])
def is_top_rated():
    return models.Q(avg_rating__gte=4.5, review_count__gte=10)
```

Annotating `is_top_rated` auto-aliases its deps. Explicitly annotating a dep promotes it.

## Composed Queries

For multi-field reusable queries:

```python
@dex.query(Recipe)
def recipe_card(qs):
    return qs.annotate(Recipe.total_time, Recipe.avg_rating, Recipe.review_count)
```

Called with: `recipe_card(Recipe.objects.filter(...)).order_by(...)`

## Prefetches

```python
# prefetches/recipe.py
@dex.prefetch()
def top_reviews():
    from myapp.models import Review
    return models.Prefetch("reviews", queryset=Review.objects.filter(score__gte=4), to_attr="top_reviews")

# models/recipe.py — bind via in-class import
class Recipe(dex.Model):
    from myapp.prefetches.recipe import top_reviews

# Usage:
Recipe.objects.prefetch_related(Recipe.top_reviews)
```

## Import Style

Use `from django.db import models` then `models.F(...)`, `models.Q(...)`, `models.Value(...)`,
`models.Subquery(...)`, `models.functions.Concat(...)`, etc.

## What NOT to Do

- Don't skip `@staticmethod` on inline expressions (causes IDE warnings)
- Don't import models at module level in expression files (circular imports)
- Don't define expressions that modify queryset state beyond their single annotation
- Don't access expression values on instances without `.annotate()` first
