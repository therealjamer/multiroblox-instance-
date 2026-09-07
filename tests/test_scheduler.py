"""Tests for the in-app scheduler: _check_scheduled_launches's firing
logic (time match, day-of-week filter, once-per-minute dedup, busy/
missing-profile skip) and _refresh_schedule_list's rendering. Time
matching is tested against the real current time (time.localtime()),
not a mocked clock - the function reads it directly and takes no time
parameter, so this locks in actual behavior rather than an assumption
about how it reads the clock.
"""
import time

import multi_roblox as mr


class FakeAppForScheduler:
    def __init__(self, profiles=("Alice",), busy=False):
        self.settings = {"scheduled_launches": []}
        self.profiles = [{"name": n} for n in profiles]
        self._schedule_last_fired = {}
        self.busy = busy
        self.logs = []
        self.launched = []

    def log(self, msg):
        self.logs.append(msg)

    def launch_profile_by_name(self, name):
        self.launched.append(name)

    def _schedule_scheduler_tick(self):
        pass  # would normally re-arm the real Tk timer; not under test here


def _check(fake):
    mr.MultiRobloxApp._check_scheduled_launches(fake)


def _now_entry(**overrides):
    now = time.localtime()
    entry = {"profile": "Alice", "hour": now.tm_hour, "minute": now.tm_min,
             "days": [], "enabled": True}
    entry.update(overrides)
    return entry


def test_fires_when_the_time_matches_right_now():
    fake = FakeAppForScheduler()
    fake.settings["scheduled_launches"] = [_now_entry()]
    _check(fake)
    assert fake.launched == ["Alice"]


def test_does_not_fire_a_second_time_within_the_same_minute():
    fake = FakeAppForScheduler()
    fake.settings["scheduled_launches"] = [_now_entry()]
    _check(fake)
    _check(fake)
    assert fake.launched == ["Alice"]


def test_disabled_entry_never_fires():
    fake = FakeAppForScheduler()
    fake.settings["scheduled_launches"] = [_now_entry(enabled=False)]
    _check(fake)
    assert fake.launched == []


def test_a_day_restricted_entry_only_fires_on_its_days():
    now_wday = time.localtime().tm_wday
    wrong_day = (now_wday + 1) % 7
    fake = FakeAppForScheduler()
    fake.settings["scheduled_launches"] = [_now_entry(days=[wrong_day])]
    _check(fake)
    assert fake.launched == []

    fake2 = FakeAppForScheduler()
    fake2.settings["scheduled_launches"] = [_now_entry(days=[now_wday])]
    _check(fake2)
    assert fake2.launched == ["Alice"]


def test_no_days_checked_means_every_day():
    fake = FakeAppForScheduler()
    fake.settings["scheduled_launches"] = [_now_entry(days=[])]
    _check(fake)
    assert fake.launched == ["Alice"]


def test_wrong_time_does_not_fire():
    now = time.localtime()
    off_hour = (now.tm_hour + 2) % 24
    fake = FakeAppForScheduler()
    fake.settings["scheduled_launches"] = [_now_entry(hour=off_hour)]
    _check(fake)
    assert fake.launched == []


def test_busy_skips_but_logs_rather_than_silently_dropping():
    fake = FakeAppForScheduler(busy=True)
    fake.settings["scheduled_launches"] = [_now_entry()]
    _check(fake)
    assert fake.launched == []
    assert any("already busy" in msg for msg in fake.logs)


def test_a_renamed_or_removed_profile_is_skipped_with_a_log():
    fake = FakeAppForScheduler(profiles=())
    fake.settings["scheduled_launches"] = [_now_entry(profile="Ghost")]
    _check(fake)
    assert fake.launched == []
    assert any("no saved profile named" in msg for msg in fake.logs)


def test_refresh_schedule_list_renders_time_profile_days_and_disabled_flag():
    import tkinter as tk
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        import pytest
        pytest.skip("no display available for a real Tk window")

    fake = FakeAppForScheduler.__new__(FakeAppForScheduler)
    fake.settings = {"scheduled_launches": [
        {"profile": "Bob", "hour": 7, "minute": 30, "days": [0, 2, 4],
         "enabled": True},
        {"profile": "Alice", "hour": 8, "minute": 0, "days": [], "enabled": True},
        {"profile": "Carol", "hour": 9, "minute": 5, "days": [], "enabled": False},
    ]}
    fake.schedule_listbox = tk.Listbox(root)
    mr.MultiRobloxApp._refresh_schedule_list(fake)
    lines = list(fake.schedule_listbox.get(0, tk.END))
    root.destroy()

    assert lines[0] == "07:30  ·  Bob  ·  Mon,Wed,Fri"
    assert lines[1] == "08:00  ·  Alice  ·  daily"
    assert lines[2] == "09:05  ·  Carol  ·  daily  ·  (disabled)"


def test_schedule_dialog_round_trips_every_field():
    import tkinter as tk
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        import pytest
        pytest.skip("no display available for a real Tk window")

    dlg = mr.ScheduleDialog(root, ["Alice", "Bob"], profile="Bob", hour=7,
                            minute=30, days=[0, 2, 4], enabled=False)
    dlg._save()
    result = dlg.result
    root.destroy()

    assert result == {"profile": "Bob", "hour": 7, "minute": 30,
                      "days": [0, 2, 4], "enabled": False}
