"""Spawn-safe worker for synthetic shared-cache login throttle tests."""


def record_failures(cache_settings, lock_path, barrier, reads, kind):
    import django

    django.setup()
    from django.core.cache import caches
    from django.test import RequestFactory, override_settings

    from python_podcast.users.login_throttle import (
        THROTTLE_CACHE_ALIAS,
        AdminLoginClientThrottle,
        AdminLoginUsernameThrottle,
    )

    with override_settings(CACHES=cache_settings, ADMIN_LOGIN_THROTTLE_LOCK_PATH=lock_path):
        if kind == "username":
            throttle = AdminLoginUsernameThrottle("synthetic-user")
        else:
            throttle = AdminLoginClientThrottle(RequestFactory().post("/", REMOTE_ADDR="192.0.2.1"))
        throttle.num_requests = 3
        backend = caches[THROTTLE_CACHE_ALIAS]
        original_get = backend.get

        def observed_get(*args, **kwargs):
            reads.put("read")
            return original_get(*args, **kwargs)

        backend.get = observed_get
        barrier.wait(timeout=30)
        throttle.record_failure()
