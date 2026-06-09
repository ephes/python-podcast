import os

import pytest

# Playwright's sync API runs an event loop on the test thread; allow the Django
# ORM to be used from the fixtures/test in that context (the live-server data is
# created synchronously). Set before Django touches the ORM.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "1")


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    # Allow audio playback to start without a separate gesture-policy hurdle in
    # headless Chromium (the test still clicks Play).
    return {
        **browser_type_launch_args,
        "args": [
            *browser_type_launch_args.get("args", []),
            "--autoplay-policy=no-user-gesture-required",
            # Use a null audio sink: the media playback clock then advances even
            # when the host's real audio output device is unavailable/wedged
            # (otherwise currentTime can stall at ~0 with paused === false).
            "--disable-audio-output",
        ],
    }


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {**browser_context_args, "viewport": {"width": 1280, "height": 900}}
