# dex - django expressions

Named, reusable ORM expressions and prefetches for Django.

You define an expression once, bind it to a model, and use it through the standard queryset methods you already know: `annotate()`, `alias()`, `filter()`, `exclude()`, `prefetch_related()`.

Note: This project is early. The core works and is tested, but the API may still shift before 1.0.

## Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Scaling Up](#scaling-up)
- [Parameterized Expressions](#parameterized-expressions)
- [Dependencies](#dependencies)
- [Filter, Exclude, and Alias](#filter-exclude-and-alias)
- [Prefetches](#prefetches)
- [Composed Queries](#composed-queries)
- [IDE Support and Safety](#ide-support-and-safety)
- [Configuration](#configuration)
- [Future](#future)
- [Summary](#summary)

## Installation

```bash
pip install django-expressions
```

Add `dex` to your Django settings:

```python
# settings.py
INSTALLED_APPS = [
    ...
    "dex",
]
```

Migrating an existing project? The [Migration Guide](MIGRATION_GUIDE.md) walks through converting managers, inline annotations, and scattered query logic to `dex` expressions.

<details>
<summary><strong>Example models used in this README</strong></summary>

```python
class Recipe(BaseModel):
    title = models.CharField(max_length=200)
    prep_minutes = models.PositiveIntegerField()
    cook_minutes = models.PositiveIntegerField()
    author = models.ForeignKey("User", on_delete=models.CASCADE, related_name="recipes")
    is_published = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

class Ingredient(BaseModel):
    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50)  # "meat", "vegetable", "dairy", etc.

class RecipeIngredient(BaseModel):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="recipe_ingredients")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    amount = models.CharField(max_length=50)  # "2 cups", "1 tbsp", etc.

class Review(BaseModel):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="reviews")
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    score = models.IntegerField()  # 1-5
    text = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class SavedRecipe(BaseModel):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="saves")
    user = models.ForeignKey("User", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

class User(BaseModel):
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200)
```

</details>

## Quick Start

### 1. Set up your base model

```python
import dex
from django.db import models

class BaseModel(dex.Model):
    class Meta:
        abstract = True
```

Or, if you prefer not to use a base class, add the manager directly:

```python
class MyModel(models.Model):
    objects = dex.Manager()
```

### 2. Define expressions

Expressions can live inline in the model class, or in separate files that the model imports in. Both work with full IDE support.

#### Inline

```python
import dex
from django.db import models

class Recipe(BaseModel):
    title = models.CharField(max_length=200)
    prep_minutes = models.PositiveIntegerField()
    cook_minutes = models.PositiveIntegerField()
    is_published = models.BooleanField(default=False)

    @staticmethod
    @dex.expression(models.IntegerField())
    def total_time():
        return models.F("prep_minutes") + models.F("cook_minutes")

    @staticmethod
    @dex.expression(models.BooleanField())
    def is_quick():
        return models.Q(prep_minutes__lte=10, cook_minutes__lte=20)
```

`@staticmethod` sits above `@dex.expression()` to suppress IDE "missing self" warnings. `dex` unwraps it automatically.

#### External with in-class imports

Define in separate files, pull them into the model class body:

```python
# expressions/recipe.py
from django.db import models
import dex

@dex.expression(models.IntegerField())
def total_time():
    return models.F("prep_minutes") + models.F("cook_minutes")

@dex.expression(models.BooleanField())
def is_quick():
    return models.Q(prep_minutes__lte=10, cook_minutes__lte=20)

@dex.expression(models.BooleanField())
def is_vegetarian():
    from myapp.models import RecipeIngredient
    return ~models.Exists(
        RecipeIngredient.objects.filter(
            recipe_id=models.OuterRef("id"),
            ingredient__category="meat",
        )
    )
```

```python
# models/recipe.py
class Recipe(BaseModel):
    title = models.CharField(max_length=200)
    prep_minutes = models.PositiveIntegerField()
    cook_minutes = models.PositiveIntegerField()
    is_published = models.BooleanField(default=False)

    # MARK: Expressions
    from expressions.recipe import total_time, is_quick, is_vegetarian
```

`Recipe.total_time` resolves in the IDE, autocomplete and go-to-definition work, and the same expression can be imported into multiple models safely (each gets its own clone).

Expression files never import the model they belong to, so no circular imports. If an expression body needs another model, use a local import inside the function.

*IDE note:* PyCharm may flag in-class imports as unused. They aren't, they become class attributes at runtime. Ruff handles this correctly. For PyCharm, add `# noinspection PyUnresolvedReferences` above the import block.

### 3. Use them with standard Django methods

```python
# Annotate adds the field to the queryset and to instances:
Recipe.objects.annotate(Recipe.total_time).filter(total_time__lte=30)

# Alias makes it available for filtering/ordering, but not on instances:
Recipe.objects.alias(Recipe.total_time).filter(total_time__lte=30)

# Q-returning expressions work directly in filter/exclude:
Recipe.objects.filter(Recipe.is_quick)
Recipe.objects.filter(Recipe.is_vegetarian)
Recipe.objects.exclude(Recipe.is_vegetarian)

# Combine freely, it's all standard Django:
(Recipe.objects
    .annotate(Recipe.total_time)
    .filter(Recipe.is_vegetarian)
    .order_by("total_time"))
```

## Scaling Up

Expressions tend to grow in place. Start inline, move to a file when the model gets busy, split that file when it gets big:

```python
class Recipe(BaseModel):
    title = models.CharField(max_length=200)
    prep_minutes = models.PositiveIntegerField()
    cook_minutes = models.PositiveIntegerField()
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    is_published = models.BooleanField(default=False)

    # MARK: Inline expressions
    @staticmethod
    @dex.expression(models.BooleanField())
    def is_draft():
        return models.Q(is_published=False)

    # MARK: Time expressions
    from expressions.recipe_time import total_time, is_quick

    # MARK: Dietary expressions
    from expressions.recipe_dietary import is_vegetarian, is_vegan, is_gluten_free

    # MARK: Rating expressions
    from expressions.recipe_rating import avg_rating, review_count, is_top_rated

    # MARK: Prefetches
    from prefetches.recipe import top_reviews, ingredients_with_amounts
```

The in-class imports double as a readable manifest of what the model supports.

### Loose expressions (unbound)

You can also register an expression on a model from outside the class body using `@Model.expression()`:

```python
# somewhere/extra.py
from myapp.models import Recipe

@Recipe.expression(models.DecimalField())
def price_per_minute():
    return models.F("price") / (models.F("prep_minutes") + models.F("cook_minutes"))
```

This attaches `price_per_minute` to `Recipe` at runtime. Because there's no in-class import, the IDE won't resolve `Recipe.price_per_minute`, so you'd import the function directly where you use it.

Loose expressions register via import side effects, so the module needs to be imported at startup. Use the `DEX` setting:

```python
DEX = {
    "MODULES": [
        "somewhere.extra",
    ],
}
```

In-class imports are usually nicer (better IDE support, self-documenting). Loose expressions are there when you need them.

## Parameterized Expressions

Expressions can take parameters, just add function arguments:

```python
# expressions/recipe.py
@dex.expression(models.BooleanField())
def is_saved(user):
    from myapp.models import SavedRecipe
    return models.Exists(
        SavedRecipe.objects.filter(
            recipe_id=models.OuterRef("id"),
            user=user,
        )
    )
```

```python
# models/recipe.py
class Recipe(BaseModel):
    ...

    # MARK: Expressions
    from expressions.recipe import is_saved
```

Call the expression with its arguments:

```python
Recipe.objects.annotate(Recipe.is_saved(request.user))
Recipe.objects.filter(Recipe.is_saved(request.user))
Recipe.objects.exclude(Recipe.is_saved(request.user))
```

## Dependencies

An expression can declare that it depends on others via `uses`:

```python
# expressions/recipe_rating.py
@dex.expression(models.DecimalField())
def avg_rating():
    from myapp.models import Review
    return models.Subquery(
        Review.objects.filter(recipe_id=models.OuterRef("id"))
        .values("recipe_id")
        .annotate(avg=models.Avg("score"))
        .values("avg")
    )

@dex.expression(models.IntegerField())
def review_count():
    from myapp.models import Review
    return models.Subquery(
        Review.objects.filter(recipe_id=models.OuterRef("id"))
        .values("recipe_id")
        .annotate(count=models.Count("id"))
        .values("count")
    )

@dex.expression(
    models.BooleanField(),
    uses=[avg_rating, review_count],
)
def is_top_rated():
    return models.Q(avg_rating__gte=4.5, review_count__gte=10)
```

Dependencies resolve automatically. Annotating `is_top_rated` applies `avg_rating` and `review_count` as *aliases*, so they're available to the query engine but not attached to instances:

```python
recipe = Recipe.objects.annotate(Recipe.is_top_rated).first()
recipe.is_top_rated    # True
recipe.avg_rating      # raises ExpressionNotAnnotated
```

If you also want a dependency on instances, annotate it explicitly. It gets promoted from alias to annotation:

```python
recipe = Recipe.objects.annotate(Recipe.avg_rating, Recipe.is_top_rated).first()
recipe.avg_rating      # 4.8
recipe.is_top_rated    # True
```

Dependencies are declared as function references, not strings, so the IDE can follow them. Intermediates listed in `uses` don't need to be imported into the model class, only things you use directly do.

### Cross-model patterns

When the same annotation applies to different models via different field paths (`F("first_name")` on User vs. `F("user__first_name")` on Membership), define separate expressions for each. Expressions are scoped to the model's field namespace.

## Filter, Exclude, and Alias

Expressions that return `Q` or `Exists` work directly in `.filter()` and `.exclude()`:

```python
Recipe.objects.filter(Recipe.is_vegetarian)
Recipe.objects.exclude(Recipe.is_quick)
Recipe.objects.filter(Recipe.is_saved(request.user))
```

Non-Q expressions (CharField, IntegerField, etc.) need `.annotate()` or `.alias()` first:

```python
# annotate, value is on instances AND available for filtering:
Recipe.objects.annotate(Recipe.total_time).filter(total_time__lte=30)

# alias, value is available for filtering but NOT on instances:
Recipe.objects.alias(Recipe.total_time).filter(total_time__lte=30)

# alias is handy when you only need to filter/sort, not display:
Recipe.objects.alias(Recipe.avg_rating).filter(avg_rating__gte=4).order_by("-avg_rating")
```

Using a non-Q expression directly in `.filter()` raises a clear error:

```
dex.FilterError: 'total_time' returns IntegerField, not a filter condition.
Use .annotate(Recipe.total_time).filter(total_time__lte=...) instead.
```

## Prefetches

Prefetches follow the same patterns as expressions.

### Inline

```python
class Recipe(BaseModel):
    @staticmethod
    @dex.prefetch()
    def top_reviews():
        from myapp.models import Review
        return models.Prefetch(
            "reviews",
            queryset=Review.objects.filter(score__gte=4).order_by("-score"),
            to_attr="top_reviews",
        )
```

### External with in-class import

```python
# prefetches/recipe.py
@dex.prefetch()
def top_reviews():
    from myapp.models import Review
    return models.Prefetch(
        "reviews",
        queryset=Review.objects.filter(score__gte=4).order_by("-score"),
        to_attr="top_reviews",
    )

@dex.prefetch()
def ingredients_with_amounts():
    from myapp.models import RecipeIngredient
    return models.Prefetch(
        "recipe_ingredients",
        queryset=RecipeIngredient.objects.select_related("ingredient"),
    )
```

```python
# models/recipe.py
class Recipe(BaseModel):
    # MARK: Prefetches
    from prefetches.recipe import top_reviews, ingredients_with_amounts
```

### Usage

```python
Recipe.objects.prefetch_related(Recipe.top_reviews)
Recipe.objects.prefetch_related(Recipe.ingredients_with_amounts)

# Combine with expressions:
(Recipe.objects
    .annotate(Recipe.avg_rating)
    .prefetch_related(Recipe.top_reviews)
    .filter(Recipe.is_vegetarian)
    .order_by("-avg_rating"))
```

## Composed Queries

For multi-field queryset patterns you want to reuse:

```python
# queries/recipe.py
import dex
from django.db import models

@dex.query(Recipe)
def recipe_card(qs):
    """The standard set of fields needed for a recipe card display."""
    return (
        qs
        .annotate(Recipe.total_time, Recipe.avg_rating, Recipe.review_count)
        .prefetch_related(Recipe.ingredients_with_amounts)
    )

@dex.query(Recipe)
def recipe_search(qs, user=None):
    """Recipe card fields plus user-specific data."""
    qs = recipe_card(qs)
    if user:
        qs = qs.annotate(Recipe.is_saved(user))
    return qs
```

```python
from queries.recipe import recipe_card, recipe_search

recipes = recipe_card(Recipe.objects.filter(Recipe.is_vegetarian))

recipes = recipe_search(Recipe.objects.all(), user=request.user)
recipes = recipes.order_by("-avg_rating")
```

The `@dex.query` decorator gives the function an identity tied to a model. Today that just lets it default to `Model.objects.all()` when called without a queryset, but it also leaves room for future materialization support (see [Future](#future)).

## IDE Support and Safety

Inline and in-class imported expressions are visible to the IDE. Autocomplete, go-to-definition, and find-usages work.

If you access an expression on an instance that wasn't annotated, you get a clear error instead of a silent `None` or `AttributeError`:

```python
recipe = Recipe.objects.first()  # no .annotate(Recipe.avg_rating)
recipe.avg_rating
# AttributeError: 'avg_rating' is a dex expression on Recipe.
# Call .annotate(Recipe.avg_rating) on the queryset first.
```

## Configuration

```python
# settings.py
DEX = {
    # Modules to import at startup (registers loose/unbound expressions)
    "MODULES": [
        "expressions",
        "prefetches",
    ],
}
```

`MODULES` is only needed for loose expressions (defined with `@Model.expression()`) that aren't imported elsewhere. In-class imports load automatically when the model does.

## Future

Planned, not yet implemented:

- **Unused annotation warnings.** Dev-mode detection of annotated fields that are never accessed on instances.
- **Materialized views.** `@dex.query` functions with `.refresh()` and `.from_cache()` for precomputing and caching query results.
- **Static analysis plugin.** mypy/pyright plugin to catch missing `.annotate()` calls at type-check time.

See [FUTURE.md](FUTURE.md) for notes on each.

## Summary

| Concept | Defines | Used in |
|---------|---------|---------|
| `dex.expression` | Named ORM expression | `.annotate()`, `.alias()`, `.filter()`, `.exclude()` |
| `dex.prefetch` | Named prefetch recipe | `.prefetch_related()` |
| `dex.query` | Composed queryset function | Called directly |
| `dex.Model` | Base model with `dex.Manager` | Model inheritance |

Everything else is standard Django.

## Further Reading

- [Migration Guide](MIGRATION_GUIDE.md), step-by-step refactoring from managers to `dex`.
