"""Tests for profile groups/tags: the group filter dropdown must stay in
sync with whatever groups actually exist, and filtering by group must
still translate listbox rows back to real profile indices correctly -
the same _profile_index_map machinery the text search filter relies on
(see test_profile_filter.py), just with a second, combined filter axis.

Uses a real Tk Listbox/Combobox (not mocks) - filtering happens by
reading their actual state, so a fake would test nothing.
"""
import tkinter as tk
from tkinter import ttk

import pytest

import multi_roblox as mr


@pytest.fixture
def app():
    try:
        root = tk.Tk()
        root.withdraw()
    except tk.TclError:
        pytest.skip("no display available for a real Tk window")

    a = mr.MultiRobloxApp.__new__(mr.MultiRobloxApp)
    a.root = root
    a.game_names = {}
    a._game_lookups = set()
    a.profiles = [
        {"name": "Alice", "group": "Farming", "cookie": ""},
        {"name": "Bob", "group": "Farming", "cookie": ""},
        {"name": "Carol", "group": "Trading", "cookie": ""},
        {"name": "Dave", "group": "", "cookie": ""},
    ]
    frame = tk.Frame(root)
    a.profile_listbox = tk.Listbox(frame, selectmode=tk.EXTENDED)
    a.profile_group_var = tk.StringVar(value="All groups")
    a.profile_group_filter = ttk.Combobox(
        frame, textvariable=a.profile_group_var, values=["All groups"])
    yield a
    root.destroy()


def _refresh(a):
    mr.MultiRobloxApp.refresh_profile_list(a)


def test_group_dropdown_lists_every_distinct_group_once_sorted(app):
    _refresh(app)
    assert tuple(app.profile_group_filter["values"]) == (
        "All groups", "Farming", "Trading")


def test_all_groups_shows_every_profile_with_a_group_prefix(app):
    _refresh(app)
    lines = list(app.profile_listbox.get(0, tk.END))
    assert len(lines) == 4
    assert lines[0].startswith("[Farming] Alice")
    assert lines[3].startswith("Dave")  # no group -> no prefix


def test_selecting_a_group_filters_the_list_and_index_map(app):
    app.profile_group_var.set("Farming")
    _refresh(app)
    lines = list(app.profile_listbox.get(0, tk.END))
    assert len(lines) == 2
    assert all("Farming" in ln for ln in lines)
    assert app._profile_index_map == [0, 1]  # Alice, Bob's real indices


def test_ungrouped_profiles_only_show_under_all_groups(app):
    app.profile_group_var.set("Trading")
    _refresh(app)
    assert list(app.profile_listbox.get(0, tk.END)) == ["[Trading] Carol  ·  guest"]


def test_group_and_text_filters_combine(app):
    app.profile_group_var.set("Farming")
    app.profile_filter_var = tk.StringVar(value="bob")
    _refresh(app)
    lines = list(app.profile_listbox.get(0, tk.END))
    assert len(lines) == 1
    assert "Bob" in lines[0]


def test_removing_the_last_profile_in_a_group_drops_it_from_the_dropdown(app):
    _refresh(app)
    assert "Trading" in app.profile_group_filter["values"]
    app.profiles = [p for p in app.profiles if p["name"] != "Carol"]
    _refresh(app)
    assert "Trading" not in app.profile_group_filter["values"]


def test_switching_away_a_now_nonexistent_group_falls_back_to_all(app):
    app.profile_group_var.set("Trading")
    _refresh(app)
    app.profiles = [p for p in app.profiles if p["name"] != "Carol"]
    _refresh(app)
    assert app.profile_group_var.get() == "All groups"
    assert len(list(app.profile_listbox.get(0, tk.END))) == 3
