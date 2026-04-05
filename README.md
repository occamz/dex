# dex — Django Expressions

A lightweight library for defining named, reusable ORM expressions and prefetches on Django models. Use them through standard Django queryset methods — `annotate()`, `alias()`, `filter()`, `exclude()`, `prefetch_related()` — no new query API to learn.

### Is this for you?

If any of these sound familiar, dex might help:

- "I keep copy-pasting the same `.annotate()` calls across views and serializers"
- "My annotations are a mess and I can't tell which model supports what"
- "Manager methods don't compose — I can't chain `.with_full_name().with_age()`"
- "Wish I could combine querysets more easily without everything breaking"
- "I have helper annotations cluttering my querysets that I only need for computing other fields"
- "I want reusable, named annotations with IDE autocomplete"

dex solves these by letting you define annotations once, bind them to models, and use them
through standard Django queryset methods. No new API to learn — just `annotate()`, `filter()`,
and `prefetch_related()` with named references instead of inline expressions.

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

> **Migrating an existing project?** See the [Migration Guide](MIGRATION_GUIDE.md) for a
> step-by-step walkthrough of converting managers, inline annotations, and scattered query
> logic to dex expressions.

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

Or, if you prefer not to use a base class:

```python
class MyModel(models.Model):
    objects = dex.Manager()
```

### 2. Define expressions

Expressions can be defined **inline** (in the model class) or **externally** (in separate
files, bound to the model via in-class imports). Both give full IDE support.

#### Inline (small projects, simple expressions)

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

> `@staticmethod` goes above `@dex.expression()` for inline expressions. This suppresses
> IDE "missing self" warnings and is automatically unwrapped by dex.

#### External with in-class imports (recommended for larger projects)

Define expressions in separate files, then import them into the model class. The imports
make them available as model attributes with full IDE support.

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

`Recipe.total_time` resolves in the IDE — autocomplete, go-to-definition, and
find-usages all work. The model class serves as a manifest of its available expressions.

The same expression can be safely imported into multiple models — each gets its own copy.

> **IDE note:** PyCharm may show "unused import" warnings on in-class imports. These are
> false positives — the imports create class attributes used at runtime. Ruff correctly
> recognizes them as used. You can suppress the PyCharm warning per-file with
> `# noinspection PyUnresolvedReferences` above the import block.

> **No circular imports:** Expression files use `@dex.expression()` (module-level), so they
> never need to import the model they belong to. If an expression body needs another model
> (e.g., for a subquery), use a local import inside the function.

### 3. Use them with standard Django methods

```python
# Annotate — adds the field to the queryset:
Recipe.objects.annotate(Recipe.total_time).filter(total_time__lte=30)

# Alias — for filtering/ordering without adding the field to instances:
Recipe.objects.alias(Recipe.total_time).filter(total_time__lte=30)

# Filter — Q-returning expressions work directly:
Recipe.objects.filter(Recipe.is_quick)
Recipe.objects.filter(Recipe.is_vegetarian)

# Exclude:
Recipe.objects.exclude(Recipe.is_vegetarian)

# Combine freely — it's all standard Django:
(Recipe.objects
    .annotate(Recipe.total_time)
    .filter(Recipe.is_vegetarian)
    .order_by("total_time"))
```

## Scaling Up

### Migration path

The progression from small to large project is gradual:

**Phase 1 — Inline:** Expressions live in the model class. Simple, quick.

**Phase 2 — External:** Expressions move to separate files as the model grows. The model
gets in-class imports that serve as a readable manifest.

**Phase 3 — Organized:** Expressions are grouped by domain into separate modules.

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

Compare this to grepping across hundreds of files to find which annotations apply to a
model — the in-class imports make it explicit.

### Loose expressions (unbound)

Expressions can be registered on a model externally using `@Model.expression()`:

```python
# somewhere/extra.py
from myapp.models import Recipe

@Recipe.expression(models.DecimalField())
def price_per_minute():
    return models.F("price") / (models.F("prep_minutes") + models.F("cook_minutes"))
```

This attaches `price_per_minute` to `Recipe` at runtime, so `Recipe.objects.annotate(Recipe.price_per_minute)` works. However, the IDE won't resolve `Recipe.price_per_minute` since it's not in the class body. Use `from somewhere.extra import price_per_minute` directly when referencing it.

Because these expressions are registered as a side effect of importing the module, you need to ensure the module is imported at startup. Use the `DEX` setting in `settings.py`:

```python
DEX = {
    "MODULES": [
        "somewhere.extra",
    ],
}
```

We recommend in-class imports over loose expressions when possible — they give better IDE support and make the model self-documenting.

## Parameterized Expressions

Expressions can accept parameters. Define them as function arguments:

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
# Annotate:
Recipe.objects.annotate(Recipe.is_saved(request.user))

# Filter:
Recipe.objects.filter(Recipe.is_saved(request.user))

# Exclude:
Recipe.objects.exclude(Recipe.is_saved(request.user))
```

## Dependencies

An expression can declare that it depends on other expressions using `uses`:

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

When you annotate `is_top_rated`, its dependencies are automatically resolved first:

```python
Recipe.objects.annotate(Recipe.is_top_rated)
# Internally: aliases avg_rating and review_count, then annotates is_top_rated
```

Dependencies are applied as **aliases** — they're available to the query engine but don't
appear on instances. Only the explicitly requested expression shows up:

```python
recipe = Recipe.objects.annotate(Recipe.is_top_rated).first()
recipe.is_top_rated    # True — explicitly annotated
recipe.avg_rating      # raises ExpressionNotAnnotated — it was only aliased

# To also get avg_rating on instances, annotate it explicitly:
recipe = Recipe.objects.annotate(Recipe.avg_rating, Recipe.is_top_rated).first()
recipe.avg_rating      # 4.8 — explicitly annotated, promoted from alias
recipe.is_top_rated    # True
```

Dependencies are:
- **Explicit** — declared right in the definition, IDE-navigable (not strings)
- **Performant** — only declared deps are included, nothing extra
- **Clean** — intermediate fields don't leak into the result set
- **Safe** — already-applied expressions are skipped (no double annotation)

## Filter, Exclude, and Alias

Expressions that return `Q` objects or `Exists` can be used directly in `.filter()` and
`.exclude()`:

```python
Recipe.objects.filter(Recipe.is_vegetarian)
Recipe.objects.exclude(Recipe.is_quick)
Recipe.objects.filter(Recipe.is_saved(request.user))
```

Non-Q expressions (e.g., `CharField`, `IntegerField`) can't be filtered directly — use
`.annotate()` or `.alias()` first:

```python
# annotate — field is on instances AND available for filtering:
Recipe.objects.annotate(Recipe.total_time).filter(total_time__lte=30)

# alias — field is available for filtering but NOT on instances:
Recipe.objects.alias(Recipe.total_time).filter(total_time__lte=30)

# alias is useful when you only need to filter/sort, not display the value:
Recipe.objects.alias(Recipe.avg_rating).filter(avg_rating__gte=4).order_by("-avg_rating")
```

Using a non-Q expression directly in `.filter()` raises a clear error:

```
dex.FilterError: 'total_time' returns IntegerField, not a filter condition.
Use .annotate(Recipe.total_time).filter(total_time__lte=...) instead.
```

## Prefetches

Named, reusable prefetch recipes follow the same patterns as expressions.

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

## Composed Queries (Layer 2)

For reusable multi-field queries that compose expressions with additional logic:

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

Usage — just call it with a queryset:

```python
from queries.recipe import recipe_card, recipe_search

# Simple:
recipes = recipe_card(Recipe.objects.filter(Recipe.is_vegetarian))

# With user context:
recipes = recipe_search(Recipe.objects.all(), user=request.user)
recipes = recipes.order_by("-avg_rating")

# Compose multiple:
recipes = recipe_card(Recipe.objects.all())
recipes = recipes.filter(Recipe.is_quick)
```

The `@dex.query` decorator gives the function an identity for future materialization support.

## IDE Support and Safety

### Autocomplete and navigation

Expressions defined inline or via in-class imports are visible to the IDE as model
attributes. Autocomplete, go-to-definition, and find-usages work.

### Missing annotation detection

If you access an expression on an instance that wasn't annotated:

```python
recipe = Recipe.objects.first()  # No .annotate(Recipe.avg_rating)
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

> **Note:** The `MODULES` setting is only needed for loose expressions (defined with
> `@Model.expression()`) that aren't imported elsewhere. In-class imported expressions are
> loaded automatically when the model is imported.

## Future

These features are planned but not yet implemented:

- **Unused annotation warnings** — dev-mode detection of annotated fields that are never accessed on instances
- **Materialized views** — `@dex.query` functions with `.refresh()` and `.from_cache()` methods for precomputing and caching query results
- **Static analysis plugin** — mypy/pyright plugin to detect missing `.annotate()` calls at type-check time

## Summary

| Concept | Define with | Use in |
|---------|------------|--------|
| `dex.expression` | Named ORM expression | `.annotate()`, `.alias()`, `.filter()`, `.exclude()` |
| `dex.prefetch` | Named prefetch recipe | `.prefetch_related()` |
| `dex.query` | Composed queryset function | Called directly |
| `dex.Model` | Base model (convenience) | Model inheritance |

Everything else is standard Django.

## Further Reading

- [Migration Guide](MIGRATION_GUIDE.md) — step-by-step refactoring from managers to dex
