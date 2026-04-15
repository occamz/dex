# migrating a django project to dex

How to refactor custom managers, inline annotations, and repeated query logic to `dex` expressions.

## Prerequisites

1. Install dex: `pip install django-expressions`
2. Add `"dex"` to `INSTALLED_APPS`
3. Create a base model, or add `dex.Manager` to existing models:

```python
# models/base.py
import dex

class BaseModel(dex.Model):
    class Meta:
        abstract = True
```

4. Update your models to inherit from this base (or add `objects = dex.Manager()` directly). If you already have a custom manager with filter methods, extend `dex.Manager` instead of `models.Manager` so the existing API keeps working:

```python
# BEFORE:
class UserManager(models.Manager):
    def active(self):
        return self.filter(deactivated_at__isnull=True)

# STEP 1, extend dex.Manager to keep existing API working:
class UserManager(dex.Manager):
    def active(self):
        return self.filter(deactivated_at__isnull=True)

# STEP 2, extract the filter into an expression, then remove the manager entirely:
@dex.expression(models.BooleanField())
def is_active():
    return models.Q(deactivated_at__isnull=True)

# Old: User.objects.active()
# New: User.objects.filter(User.is_active)
```

## Step 1: Identify Candidates

Look for these patterns:

### Manager methods that annotate

```python
class UserManager(models.Manager):
    def with_full_name(self):
        return self.annotate(
            full_name=Concat(F("first_name"), Value(" "), F("last_name"))
        )
```

### Annotations duplicated across views

```python
# views/profile.py
users = User.objects.annotate(full_name=Concat(...))

# views/admin.py
users = User.objects.annotate(full_name=Concat(...))  # duplicated
```

### Large manager methods that bundle many annotations

```python
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
def thread_list(request):
    posts = Post.objects.filter(parent=None).annotate(
        reply_count=Subquery(
            Post.objects.filter(parent_id=OuterRef("id"))
            .values("parent").annotate(c=Count("id")).values("c")
        )
    )
```

## Step 2: Extract Single-Field Expressions

Each annotation becomes a `@dex.expression()`.

### Simple annotation

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

### Q-based filter

```python
# BEFORE (in view):
users = User.objects.filter(deactivated_at__isnull=True)

# AFTER (expressions/user.py):
@dex.expression(models.BooleanField())
def is_active():
    return models.Q(deactivated_at__isnull=True)
```

### Subquery annotation

```python
# BEFORE:
posts.annotate(
    reply_count=Subquery(
        Post.objects.filter(parent_id=OuterRef("id"))
        .values("parent").annotate(c=Count("id")).values("c")
    )
)

# AFTER (expressions/post.py):
@dex.expression(models.IntegerField())
def reply_count():
    from myapp.models import Post
    return models.Subquery(
        Post.objects.filter(parent_id=models.OuterRef("id"))
        .values("parent")
        .annotate(c=models.Count("id"))
        .values("c")
    )
```

Use local imports inside the function body to avoid circular imports.

### Parameterized annotation

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
    from myapp.models import ReadReceipt
    return models.Exists(
        ReadReceipt.objects.filter(post_id=models.OuterRef("id"), user=user)
    )
```

## Step 3: Bind Expressions to Models

Add in-class imports to each model:

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

`User.full_name`, `User.is_active`, `Post.reply_count`, etc. now resolve in the IDE.

## Step 4: Replace Usage Sites

### Manager method calls

```python
# BEFORE:
User.objects.with_full_name().filter(full_name__icontains="john")

# AFTER (annotate, value on instances):
User.objects.annotate(User.full_name).filter(full_name__icontains="john")

# AFTER (alias, only for filtering):
User.objects.alias(User.full_name).filter(full_name__icontains="john")
```

### Filter conditions

```python
# BEFORE:
User.objects.filter(deactivated_at__isnull=True)

# AFTER:
User.objects.filter(User.is_active)
```

### Parameterized expressions

```python
# BEFORE:
posts = Post.objects.with_is_read(request.user)

# AFTER:
posts = Post.objects.annotate(Post.is_read(request.user))
```

## Step 5: Identify Dependencies

When one annotation depends on another:

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

`trimmed_name` is applied as an alias, available to the query engine but not on instances. Intermediates in `uses` don't need to be imported into the model class, only expressions you use directly do.

## Step 6: Extract Composed Queries

Manager methods that bundle annotations become `@dex.query`:

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

The individual expressions are still independently usable.

Composed queries can take parameters. Extra arguments are forwarded after the queryset:

```python
# BEFORE:
class UserManager(models.Manager):
    def with_milestone_birthday(self, reference_date):
        return self.annotate(age_this_year=..., is_milestone=..., birthday_date=...)

# AFTER:
@dex.query(User)
def milestone_birthday(qs, reference_date):
    return qs.annotate(...)

# Usage:
milestone_birthday(User.objects.all(), reference_date=ref_date)
```

## Step 7: Extract Prefetches

```python
# BEFORE:
posts = Post.objects.prefetch_related(
    Prefetch("revisions", queryset=PostRevision.objects.filter(is_latest=True))
)

# AFTER (prefetches/post.py):
@dex.prefetch()
def latest_revisions():
    from myapp.models import PostRevision
    return models.Prefetch(
        "revisions",
        queryset=PostRevision.objects.filter(is_latest=True),
        to_attr="latest_revisions",
    )
```

Bind to the model:

```python
# models/post.py
class Post(BaseModel):
    # MARK: Prefetches
    from prefetches.post import latest_revisions

# Usage:
Post.objects.prefetch_related(Post.latest_revisions)
```

## Step 8: Clean Up

1. **Remove old managers.** If a manager only existed for annotation and filter methods, its logic now lives in expressions. Delete the manager class and use `dex.Model` or `objects = dex.Manager()` directly.
2. **Remove duplicated annotations.** They live in one place now.
3. **Update tests.** Replace `Post.objects.as_threads()` with `thread_overview(Post.objects.all())` or `Post.objects.annotate(Post.title, ...)`.
4. **Verify.** Run the test suite and check that annotations produce the same results.

## Checklist

- [ ] Base model set up with `dex.Model` or `dex.Manager`
- [ ] Single-field annotations extracted to `@dex.expression()`
- [ ] Expressions bound to models via in-class imports
- [ ] Manager method calls replaced with `.annotate(Model.expr)` / `.filter(Model.expr)`
- [ ] Inline view annotations replaced with expression references
- [ ] Dependencies declared with `uses`
- [ ] Large manager methods converted to `@dex.query`
- [ ] Prefetch patterns converted to `@dex.prefetch()`
- [ ] Old manager classes removed
- [ ] Tests passing
