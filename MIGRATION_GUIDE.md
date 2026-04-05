# Migrating a Django Project to dex

This guide walks through refactoring a Django project that uses custom managers,
inline annotations, and repeated query logic into dex's composable expression system.

## Prerequisites

1. Install dex: `pip install django-expressions`
2. Add `"dex"` to `INSTALLED_APPS`
3. Create a base model (or add `dex.Manager` to existing models):

```python
# models/base.py
import dex

class BaseModel(dex.Model):
    class Meta:
        abstract = True
```

4. Update your models to inherit from this base (or add `objects = dex.Manager()` directly).

## Step 1: Identify Candidates

Look for these patterns in your codebase — they're refactoring candidates:

### Manager methods that annotate

```python
# BEFORE: Manager method
class UserManager(models.Manager):
    def with_full_name(self):
        return self.annotate(
            full_name=Concat(F("first_name"), Value(" "), F("last_name"))
        )
```

### Annotations duplicated across views

```python
# BEFORE: Same annotation in multiple places
# views/profile.py
users = User.objects.annotate(full_name=Concat(...))

# views/admin.py
users = User.objects.annotate(full_name=Concat(...))  # duplicated
```

### Large manager methods that bundle many annotations

```python
# BEFORE: Manager method with 5+ annotations
class PostManager(models.Manager):
    def as_threads(self):
        return self.annotate(
            title=Subquery(...),
            body=Subquery(...),
            reply_count=Subquery(...),
            latest_activity=Subquery(...),
        )
```

### Inline annotations in views

```python
# BEFORE: Business logic in the view
def thread_list(request):
    posts = Post.objects.filter(parent=None).annotate(
        reply_count=Subquery(
            Post.objects.filter(parent_id=OuterRef("id"))
            .values("parent").annotate(c=Count("id")).values("c")
        )
    )
```

## Step 2: Extract Single-Field Expressions

Each annotation becomes a `@dex.expression()` in a separate file.

### Simple annotation → expression

```python
# BEFORE (in manager):
def with_full_name(self):
    return self.annotate(
        full_name=Concat(F("first_name"), Value(" "), F("last_name"))
    )

# AFTER (expressions/user.py):
@dex.expression(models.CharField())
def full_name():
    return models.functions.Concat(
        models.F("first_name"), models.Value(" "), models.F("last_name")
    )
```

### Q-based filter → filterable expression

```python
# BEFORE (in view):
users = User.objects.filter(deactivated_at__isnull=True)

# AFTER (expressions/user.py):
@dex.expression(models.BooleanField())
def is_active():
    return models.Q(deactivated_at__isnull=True)
```

### Subquery annotation → expression

```python
# BEFORE (in manager or view):
posts.annotate(
    reply_count=Subquery(
        Post.objects.filter(parent_id=OuterRef("id"))
        .values("parent").annotate(c=Count("id")).values("c")
    )
)

# AFTER (expressions/post.py):
@dex.expression(models.IntegerField())
def reply_count():
    from community.models import Post
    return models.Subquery(
        Post.objects.filter(parent_id=models.OuterRef("id"))
        .values("parent")
        .annotate(c=models.Count("id"))
        .values("c")
    )
```

Note: Use local imports inside the function body to avoid circular imports when referencing
your own models.

### Parameterized annotation → parameterized expression

```python
# BEFORE (in manager):
def with_is_read(self, user):
    return self.annotate(
        is_read=Exists(
            ReadReceipt.objects.filter(post_id=OuterRef("id"), user=user)
        )
    )

# AFTER (expressions/post.py):
@dex.expression(models.BooleanField())
def is_read(user):
    from community.models import ReadReceipt
    return models.Exists(
        ReadReceipt.objects.filter(post_id=models.OuterRef("id"), user=user)
    )
```

## Step 3: Bind Expressions to Models

Add in-class imports to each model — this makes expressions available as `Model.attr`
with full IDE support.

```python
# models/user.py
class User(BaseModel):
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    deactivated_at = models.DateTimeField(null=True)

    # MARK: Expressions
    from expressions.user import full_name, is_active

# models/post.py
class Post(BaseModel):
    title = models.CharField(max_length=200)
    parent = models.ForeignKey("self", null=True, on_delete=models.CASCADE)

    # MARK: Expressions
    from expressions.post import reply_count, is_read
```

Now `User.full_name`, `User.is_active`, `Post.reply_count`, etc. all resolve in the IDE.

## Step 4: Replace Usage Sites

### Manager method calls → annotate/filter with expressions

```python
# BEFORE:
User.objects.with_full_name().filter(full_name__icontains="john")

# AFTER (annotate — value available on instances):
User.objects.annotate(User.full_name).filter(full_name__icontains="john")

# AFTER (alias — only used for filtering, not on instances):
User.objects.alias(User.full_name).filter(full_name__icontains="john")
```

### Filter conditions → filter with expressions

```python
# BEFORE:
User.objects.filter(deactivated_at__isnull=True)

# AFTER:
User.objects.filter(User.is_active)
```

### Parameterized expressions in views

```python
# BEFORE:
posts = Post.objects.with_is_read(request.user)

# AFTER:
posts = Post.objects.annotate(Post.is_read(request.user))
```

## Step 5: Identify Dependencies

Look for expressions where one annotation depends on another:

```python
# BEFORE (manager bundles intermediates):
def with_full_name(self):
    return self.annotate(
        _trimmed=Trim(Concat(F("first_name"), Value(" "), F("last_name"))),
        full_name=Case(When(_trimmed="", then=F("email")), default=F("_trimmed")),
    )
```

Split into two expressions with `uses`:

```python
# expressions/user.py
@dex.expression(models.CharField())
def trimmed_name():
    return models.functions.Trim(
        models.functions.Concat(
            models.F("first_name"), models.Value(" "), models.F("last_name")
        )
    )

@dex.expression(models.CharField(), uses=[trimmed_name])
def full_name():
    return models.Case(
        models.When(trimmed_name="", then=models.F("email")),
        default=models.F("trimmed_name"),
    )
```

The `trimmed_name` dependency is applied as an alias — it exists for the query engine but
doesn't appear on instances. Only `full_name` is visible.

## Step 6: Extract Composed Queries

Large manager methods that bundle many annotations become `@dex.query`:

```python
# BEFORE (manager):
class PostManager(models.Manager):
    def as_threads(self):
        return self.annotate(title=..., body=..., reply_count=..., latest_activity=...)

# Usage:
Post.objects.as_threads().filter(group=group).order_by("-latest_activity")

# AFTER (queries/post.py):
@dex.query(Post)
def thread_overview(qs):
    return qs.annotate(Post.title, Post.body, Post.reply_count, Post.latest_activity)

# Usage:
thread_overview(Post.objects.filter(group=group)).order_by("-latest_activity")
```

The individual expressions (`title`, `reply_count`, etc.) are still independently usable.
The composed query is just a convenience for the common combination.

## Step 7: Extract Prefetches

Named prefetch patterns become `@dex.prefetch()`:

```python
# BEFORE (in view):
posts = Post.objects.prefetch_related(
    Prefetch("revisions", queryset=PostRevision.objects.filter(is_latest=True))
)

# AFTER (prefetches/post.py):
@dex.prefetch()
def latest_revisions():
    from community.models import PostRevision
    return models.Prefetch(
        "revisions",
        queryset=PostRevision.objects.filter(is_latest=True),
        to_attr="latest_revisions",
    )
```

Bind it to the model, same as expressions:

```python
# models/post.py
class Post(BaseModel):
    # MARK: Prefetches
    from prefetches.post import latest_revisions
```

```python
# Usage:
Post.objects.prefetch_related(Post.latest_revisions)
```

## Step 8: Clean Up

1. **Remove old managers** — if a manager only existed for annotation methods, replace it
   with `dex.Manager` (or inherit from `dex.Model`)
2. **Remove duplicated annotations** — they now live in one place
3. **Update tests** — replace `Post.objects.as_threads()` with
   `thread_overview(Post.objects.all())` or `Post.objects.annotate(Post.title, ...)`
4. **Verify** — run your test suite, check that all annotations produce the same results

## Checklist

- [ ] Base model set up with `dex.Model` or `dex.Manager`
- [ ] Single-field annotations extracted to `@dex.expression()`
- [ ] Expressions bound to models via in-class imports
- [ ] Manager method calls replaced with `.annotate(Model.expr)` / `.filter(Model.expr)`
- [ ] Inline view annotations replaced with expression references
- [ ] Dependencies declared with `uses` (intermediates aliased, not leaked)
- [ ] Large manager methods converted to `@dex.query`
- [ ] Prefetch patterns converted to `@dex.prefetch()`
- [ ] Old manager classes removed or simplified
- [ ] Tests updated and passing
