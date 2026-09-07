"""Regression test for a real bug found in the field: launch_method_learned
could get stuck on a method that used to work but stopped (Roblox changed
something server-side that broke the "uri" launch style specifically),
because the settle-time check that decides "did this method work" wasn't
long enough to catch a failure that landed a few seconds in. Once learned,
`auto` mode kept reusing the broken method forever.

The fix has two parts, both covered here:
  1. A method that was the REMEMBERED one but just failed gets forgotten,
     so the next launch tries everything fresh instead of repeating it.
  2. Whatever DOES work gets learned in its place.
"""
import threading

import multi_roblox as mr


class FakeAppForLaunchMethod:
    def __init__(self, learned="uri"):
        self.settings = dict(mr.DEFAULT_SETTINGS)
        self.settings["launch_method"] = "auto"
        self.settings["launch_method_learned"] = learned
        self._ticket_lock = threading.Lock()
        self._last_ticket_at = 0.0
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)


def _patch_common(monkeypatch):
    monkeypatch.setattr(mr, "find_roblox_exe", lambda: "C:\\fake\\RobloxPlayerBeta.exe")
    monkeypatch.setattr(mr, "get_auth_ticket", lambda cookie, log=None: ("fake-ticket", "ok"))
    monkeypatch.setattr(mr, "detect_launch_handler", lambda: (None, None))
    monkeypatch.setattr(mr, "get_roblox_processes", lambda: [])
    monkeypatch.setattr(mr.subprocess, "Popen", lambda cmd: None)


def _launch(fake, **profile_kwargs):
    profile = {"cookie": "x", "place_id": "", "link_code": "", "job_id": ""}
    profile.update(profile_kwargs)
    return mr.MultiRobloxApp._try_launch_signed_in(fake, profile)


def test_a_failing_learned_method_gets_forgotten(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(mr, "build_launch_command", lambda *a, **kw: ["fake.exe"])
    # Every method fails in this test.
    FakeAppForLaunchMethod._await_new_client = lambda self, before, seconds: None

    fake = FakeAppForLaunchMethod(learned="uri")
    result = _launch(fake)

    assert result is None
    assert fake.settings.get("launch_method_learned") is None
    assert any("forgetting it" in msg for msg in fake.logs)


def test_a_different_working_method_gets_learned_in_its_place(monkeypatch):
    _patch_common(monkeypatch)
    current_method = {}

    def fake_build(exe, ticket, method, *a, **kw):
        current_method["m"] = method
        return ["fake.exe", method]
    monkeypatch.setattr(mr, "build_launch_command", fake_build)

    # "uri" (the stuck-learned method) fails; "legacy" succeeds with PID 999.
    def fake_await(self, before, seconds):
        return 999 if current_method.get("m") == "legacy" else None
    FakeAppForLaunchMethod._await_new_client = fake_await

    fake = FakeAppForLaunchMethod(learned="uri")
    result = _launch(fake)

    assert result == 999
    assert fake.settings.get("launch_method_learned") == "legacy"


def test_settle_time_is_generous_enough_for_a_delayed_failure(monkeypatch):
    # The actual bug: Roblox's installer/relaunch hand-off can fail ~4
    # seconds after the process appears - well past what used to be a
    # 2-second settle check. This asserts the settle time is comfortably
    # past that, so this specific regression can't silently come back.
    import inspect
    source = inspect.getsource(mr.MultiRobloxApp._await_new_client)
    assert "time.sleep(5.0)" in source, (
        "the settle-time sleep in _await_new_client got changed - make sure "
        "it's still well past the ~4s delayed-failure window described in "
        "the function's own docstring before shortening it")
