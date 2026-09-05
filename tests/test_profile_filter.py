"""Regression test for the profile search/filter box.

Filtering means listbox row numbers no longer match self.profiles indices
directly - refresh_profile_list()/_selected_profile_indices() have to
translate through _profile_index_map. This was manually verified against a
real tk.Listbox during development; encoded here so it stays correct.

Needs a real Tk root (an actual window isn't shown - it's withdrawn), which
is why this runs on windows-latest in CI rather than a headless Linux
runner without a display.
"""
import tkinter as tk

import pytest

import multi_roblox as mr


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


class FakeAppForFilter:
    def __init__(self, root, profiles):
        self.profiles = profiles
        self.profile_listbox = tk.Listbox(root, selectmode=tk.EXTENDED)
        self.profile_filter_var = tk.StringVar(value="")
        self._profile_index_map = []


def _profiles(*names):
    return [{"name": n} for n in names]


def test_unfiltered_map_is_identity(tk_root):
    fake = FakeAppForFilter(tk_root, _profiles("Alpha", "Beta", "Gamma"))
    mr.MultiRobloxApp.refresh_profile_list(fake)
    assert fake._profile_index_map == [0, 1, 2]
    assert fake.profile_listbox.size() == 3


def test_filter_hides_non_matching_rows(tk_root):
    fake = FakeAppForFilter(
        tk_root, _profiles("Alpha", "Beta Farm", "Gamma", "Delta Farm", "Epsilon"))
    fake.profile_filter_var.set("farm")
    mr.MultiRobloxApp.refresh_profile_list(fake)
    assert fake._profile_index_map == [1, 3]
    assert fake.profile_listbox.size() == 2


def test_selecting_a_filtered_row_maps_back_to_the_real_profile(tk_root):
    fake = FakeAppForFilter(
        tk_root, _profiles("Alpha", "Beta Farm", "Gamma", "Delta Farm", "Epsilon"))
    fake.profile_filter_var.set("farm")
    mr.MultiRobloxApp.refresh_profile_list(fake)

    # Row 1 in the FILTERED view is "Delta Farm" (real index 3), not
    # whatever self.profiles[1] happens to be ("Beta Farm").
    fake.profile_listbox.selection_set(1)
    real_indices = mr.MultiRobloxApp._selected_profile_indices(fake)
    assert real_indices == [3]
    assert fake.profiles[real_indices[0]]["name"] == "Delta Farm"


def test_reselect_after_clearing_filter(tk_root):
    fake = FakeAppForFilter(
        tk_root, _profiles("Alpha", "Beta Farm", "Gamma", "Delta Farm", "Epsilon"))
    fake.profile_filter_var.set("")
    mr.MultiRobloxApp.refresh_profile_list(fake)
    mr.MultiRobloxApp._reselect_profile(fake, 3)
    assert fake.profile_listbox.curselection() == (3,)
