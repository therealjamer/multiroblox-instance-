"""Tests for _check_hung_instances's tracking/threshold logic, with
is_window_hung mocked out - a real hang takes Windows itself ~5+ seconds
to even start reporting (verified manually against a real window during
development), which would make the suite slow and flaky. The mocked
logic here is what was actually verified against a real hang; this locks
in the timing/threshold behavior around it.
"""
import time

import multi_roblox as mr


class FakeAppForHang:
    def __init__(self, enabled=True, threshold=5, labels=None):
        self.settings = {"hang_detection_enabled": enabled,
                         "hang_kill_after_seconds": threshold}
        self.pid_labels = labels if labels is not None else {111: "Main"}
        self._hang_since = {}
        self.logs = []
        self.killed = []

    def log(self, msg):
        self.logs.append(msg)


def _check(fake):
    mr.MultiRobloxApp._check_hung_instances(fake)


def test_disabled_does_nothing_and_clears_any_stale_tracking(monkeypatch):
    monkeypatch.setattr(mr, "get_window_map", lambda: {111: (999, "t")})
    monkeypatch.setattr(mr, "is_window_hung", lambda hwnd: True)
    fake = FakeAppForHang(enabled=False)
    fake._hang_since[111] = time.time() - 100  # pretend it was already tracked
    _check(fake)
    assert fake._hang_since == {}
    assert fake.killed == []


def test_first_detection_only_starts_the_clock(monkeypatch):
    monkeypatch.setattr(mr, "get_window_map", lambda: {111: (999, "t")})
    monkeypatch.setattr(mr, "is_window_hung", lambda hwnd: True)
    monkeypatch.setattr(mr.psutil, "Process",
                        lambda pid: (_ for _ in ()).throw(AssertionError(
                            "should not kill on the very first detection")))
    fake = FakeAppForHang(threshold=5)
    _check(fake)
    assert 111 in fake._hang_since


def test_kills_once_threshold_elapsed_while_still_hung(monkeypatch):
    monkeypatch.setattr(mr, "get_window_map", lambda: {111: (999, "t")})
    monkeypatch.setattr(mr, "is_window_hung", lambda hwnd: True)

    class FakeProc:
        def __init__(self, pid):
            self.pid = pid
        def kill(self):
            fake.killed.append(self.pid)
    monkeypatch.setattr(mr.psutil, "Process", FakeProc)

    fake = FakeAppForHang(threshold=5)
    fake._hang_since[111] = time.time() - 6  # already hung for 6s > 5s threshold
    _check(fake)
    assert fake.killed == [111]
    assert 111 not in fake._hang_since  # cleared after acting on it


def test_recovering_before_threshold_clears_tracking(monkeypatch):
    monkeypatch.setattr(mr, "get_window_map", lambda: {111: (999, "t")})
    monkeypatch.setattr(mr, "is_window_hung", lambda hwnd: False)  # responsive again
    fake = FakeAppForHang(threshold=5)
    fake._hang_since[111] = time.time() - 2  # was hung, but not anymore
    _check(fake)
    assert 111 not in fake._hang_since


def test_only_watches_windows_this_app_actually_launched(monkeypatch):
    # PID 222 has a window but was never launched by this app (not in
    # pid_labels) - must be ignored entirely, hung or not.
    monkeypatch.setattr(mr, "get_window_map", lambda: {222: (999, "someone else")})
    monkeypatch.setattr(mr, "is_window_hung", lambda hwnd: True)
    fake = FakeAppForHang(threshold=5, labels={111: "Main"})
    _check(fake)
    assert fake._hang_since == {}


def test_threshold_has_a_five_second_floor(monkeypatch):
    # A tiny configured threshold must not let this kill something that's
    # only been hung for a moment (e.g. a real loading-screen blip).
    monkeypatch.setattr(mr, "get_window_map", lambda: {111: (999, "t")})
    monkeypatch.setattr(mr, "is_window_hung", lambda hwnd: True)
    monkeypatch.setattr(mr.psutil, "Process",
                        lambda pid: (_ for _ in ()).throw(AssertionError(
                            "should not kill - only 2s hung, floor is 5s")))
    fake = FakeAppForHang(threshold=1)  # asks for 1s, floor clamps it to 5s
    fake._hang_since[111] = time.time() - 2
    _check(fake)
