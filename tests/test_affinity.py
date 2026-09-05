"""_next_affinity is a method (needs self.settings / self._affinity_cursor),
so it's tested against a minimal fake object rather than a real
MultiRobloxApp - same approach as testing launch_profile_by_name.

The core scenario here (masks == [0], [2], [4], [6] on a 6-physical/12-
logical machine) was manually verified against this repo's actual CPU
topology before being written up as a permanent test.
"""
import multi_roblox as mr


class FakeAppForAffinity:
    def __init__(self, spread=True, smt_ratio=1):
        self.settings = {"spread_affinity": spread}
        self._affinity_cursor = 0
        self._smt_ratio_value = smt_ratio

    def _smt_ratio(self):
        return self._smt_ratio_value


def test_spreads_across_physical_cores_not_logical_siblings(monkeypatch):
    # 6 physical / 12 logical cores, ratio 2 - matches a real Ryzen/Intel
    # 6-core-12-thread layout.
    monkeypatch.setattr(mr.os, "cpu_count", lambda: 12)
    fake = FakeAppForAffinity(spread=True, smt_ratio=2)
    next_affinity = mr.MultiRobloxApp._next_affinity

    masks = [next_affinity(fake, 1) for _ in range(4)]
    # NOT [0], [1], [2], [3] - that would put instances 0 and 1 on the same
    # physical core's two hyperthread siblings.
    assert masks == [[0], [2], [4], [6]]


def test_spreading_off_returns_a_plain_sequential_range(monkeypatch):
    monkeypatch.setattr(mr.os, "cpu_count", lambda: 12)
    fake = FakeAppForAffinity(spread=False)
    next_affinity = mr.MultiRobloxApp._next_affinity
    assert next_affinity(fake, 3) == [0, 1, 2]


def test_no_smt_behaves_like_plain_sequential_spread(monkeypatch):
    monkeypatch.setattr(mr.os, "cpu_count", lambda: 8)
    fake = FakeAppForAffinity(spread=True, smt_ratio=1)
    next_affinity = mr.MultiRobloxApp._next_affinity
    masks = [next_affinity(fake, 2) for _ in range(3)]
    assert masks == [[0, 1], [2, 3], [4, 5]]


def test_cursor_wraps_around_total_cores(monkeypatch):
    monkeypatch.setattr(mr.os, "cpu_count", lambda: 4)
    fake = FakeAppForAffinity(spread=True, smt_ratio=1)
    next_affinity = mr.MultiRobloxApp._next_affinity
    masks = [next_affinity(fake, 2) for _ in range(3)]
    assert masks == [[0, 1], [2, 3], [0, 1]]  # wraps back to the start
