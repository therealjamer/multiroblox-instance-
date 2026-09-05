"""Regression test for _apply_low_end_preset.

This caught a real bug during development: _on_setting_changed() re-derives
EVERY setting from ALL its Tk variables each time any single one fires, so
calling several var.set()s in a row let an early one re-sync a not-yet-
updated var back into self.settings, silently discarding a value that had
already been set correctly moments earlier (launch_stagger came back as
3.0 instead of the intended 5.0). Needs a real MultiRobloxApp instance,
since the bug is specifically about how its many Tk variables interact.
"""
import tkinter as tk

import pytest

import multi_roblox as mr


@pytest.fixture
def app(monkeypatch, tmp_path):
    # Keep this test's settings.json out of the real %AppData% config dir.
    monkeypatch.setattr(mr, "config_dir", lambda: str(tmp_path))
    root = tk.Tk()
    root.withdraw()
    mr.apply_appearance_settings(root)
    application = mr.MultiRobloxApp(root, None)
    monkeypatch.setattr(mr.messagebox, "askyesno", lambda *a, **kw: True)
    yield application
    root.destroy()


def test_preset_applies_all_expected_values(app):
    app._apply_low_end_preset()

    assert app.settings["cores"] == 1
    assert app.settings["cpu_percent_limit"] == 50
    assert app.settings["fps_cap"] == "30"
    assert app.settings["background_priority"] is True
    assert app.settings["mute_background"] is True
    assert app.settings["spread_affinity"] is True
    assert app.settings["refresh_interval_seconds"] == 6.0
    assert app.settings["launch_stagger"] == 5.0


def test_preset_values_survive_reload_from_disk(app):
    app._apply_low_end_preset()
    reloaded = mr.load_settings()
    assert reloaded["launch_stagger"] == 5.0
    assert reloaded["refresh_interval_seconds"] == 6.0
    assert reloaded["cores"] == 1


def test_preset_does_not_lower_an_already_larger_stagger(app):
    app.settings["launch_stagger"] = 12.0
    app._apply_low_end_preset()
    assert app.settings["launch_stagger"] == 12.0


def test_declining_the_confirmation_changes_nothing(app, monkeypatch):
    original_cores = app.settings["cores"]
    monkeypatch.setattr(mr.messagebox, "askyesno", lambda *a, **kw: False)
    app._apply_low_end_preset()
    assert app.settings["cores"] == original_cores
