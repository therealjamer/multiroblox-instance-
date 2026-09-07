"""Tests for bulk_import_profiles's line-parsing, name-collision handling
and warning summary. BulkImportDialog itself needs a real Tk window (it's
just a Text box), so these test the app-side handling of its result -
a list of (name, cookie) tuples - which is where the actual logic lives.
"""
import multi_roblox as mr


GOOD_COOKIE = "_|WARNING:-DO-NOT-SHARE-THIS." + "x" * 200


class FakeAppForBulkImport:
    def __init__(self, existing_names=()):
        self.storage_enabled = True
        self.profiles = [{"name": n} for n in existing_names]
        self.logs = []

    def log(self, msg):
        self.logs.append(msg)

    def refresh_profile_list(self):
        pass

    def _persist_profiles(self):
        return True


def _import(fake, entries):
    class FakeDlg:
        result = entries
    import multi_roblox as mrmod
    orig = mrmod.BulkImportDialog
    try:
        mrmod.BulkImportDialog = lambda master: FakeDlg()
        fake.root = None

        class FakeRoot:
            def wait_window(self, dlg):
                pass
        fake.root = FakeRoot()
        mrmod.MultiRobloxApp.bulk_import_profiles(fake)
    finally:
        mrmod.BulkImportDialog = orig


def test_imports_each_entry_as_a_new_profile():
    fake = FakeAppForBulkImport()
    _import(fake, [("Alice", GOOD_COOKIE), ("Bob", GOOD_COOKIE)])
    assert [p["name"] for p in fake.profiles] == ["Alice", "Bob"]
    assert all(p["cookie"] == GOOD_COOKIE for p in fake.profiles)


def test_name_collision_with_an_existing_profile_gets_suffixed():
    fake = FakeAppForBulkImport(existing_names=["Alice"])
    _import(fake, [("Alice", GOOD_COOKIE)])
    assert [p["name"] for p in fake.profiles] == ["Alice", "Alice (2)"]


def test_name_collisions_within_the_pasted_batch_also_get_suffixed():
    fake = FakeAppForBulkImport()
    _import(fake, [("Bob", GOOD_COOKIE), ("Bob", GOOD_COOKIE), ("Bob", GOOD_COOKIE)])
    assert [p["name"] for p in fake.profiles] == ["Bob", "Bob (2)", "Bob (3)"]


def test_new_profiles_use_the_same_schema_as_a_normal_add():
    fake = FakeAppForBulkImport()
    _import(fake, [("Alice", GOOD_COOKIE)])
    p = fake.profiles[0]
    for key in ("place_id", "link_code", "job_id", "auto_rejoin",
               "allow_guest_fallback", "cores", "monitor"):
        assert key in p


def test_short_or_malformed_cookies_are_counted_and_summarised_not_blocked():
    fake = FakeAppForBulkImport()
    _import(fake, [("Alice", "tooshort"), ("Bob", GOOD_COOKIE)])
    # Both still get imported - no per-line confirmation dialog for a bulk paste.
    assert len(fake.profiles) == 2
    assert any("1 looked malformed or short" in msg for msg in fake.logs)


def test_disabled_storage_does_nothing(monkeypatch):
    fake = FakeAppForBulkImport()
    fake.storage_enabled = False
    called = []
    monkeypatch.setattr(mr, "BulkImportDialog",
                        lambda master: called.append(1) or None)
    mr.MultiRobloxApp.bulk_import_profiles(fake)
    assert called == []
    assert fake.profiles == []
