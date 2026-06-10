import pytest


@pytest.fixture(autouse=True)
def _use_locmem_cache(settings):
    """Override the Redis cache with LocMemCache for all tests.

    Prevents tests from needing a live Redis connection for cache operations
    (e.g. the pull_all_categories lock). pytest-django's ``settings`` fixture
    triggers Django's setting_changed signal, which resets the cache framework
    to a fresh LocMemCache instance for each test — so lock state never leaks
    between tests.
    """
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    from django.core.cache import cache
    cache.clear()  # LocMemCache uses a module-level shared dict; clear it so lock state
    # from a previous test does not bleed into this one.
