"""Tests for the auto-download-and-verify updater: fetch_latest_release's
GitHub API response parsing (asset URL, SHA-256 pulled out of the release
notes body that release.yml writes) and download_verified_update's actual
byte-for-byte download + hash check, using a real temp directory and a
real hashlib.sha256 - only the network call (requests.get) is faked, so
the file I/O and hash comparison are exercised for real.

Deliberately NOT testing any self-replace/silent-install behavior: this
updater never touches the running exe or launches the download - it
verifies a file and hands the path back, on purpose (see
download_verified_update's own docstring for why).
"""
import hashlib
import os

import multi_roblox as mr


class FakeResponse:
    ok = True
    status_code = 200

    def __init__(self, json_data=None, content=None, ok=True, status_code=200):
        self._json = json_data
        self._content = content or b""
        self.headers = {"content-length": str(len(self._content))}
        self.ok = ok
        self.status_code = status_code

    def json(self):
        return self._json

    def iter_content(self, chunk_size):
        c = self._content
        for i in range(0, len(c), chunk_size):
            yield c[i:i + chunk_size]


def _release_json(tag="v99.0", sha256=None, with_asset=True):
    return {
        "tag_name": tag,
        "html_url": "https://github.com/some/repo/releases/tag/" + tag,
        "assets": ([{"name": "MultiRoblox.exe",
                    "browser_download_url": "https://example.com/MultiRoblox.exe"}]
                  if with_asset else []),
        "body": ("SHA-256 of MultiRoblox.exe: %s\n\nnotes" % sha256) if sha256 else "notes",
    }


def _install_fake_get(monkeypatch, release_json, asset_content=b""):
    def fake_get(url, headers=None, timeout=None, stream=None):
        if "api.github.com" in url:
            return FakeResponse(json_data=release_json)
        return FakeResponse(content=asset_content)
    monkeypatch.setattr(mr.requests, "get", fake_get)


def test_fetch_latest_release_parses_version_asset_and_sha(monkeypatch):
    monkeypatch.setattr(mr, "GITHUB_REPO", "some/repo")
    payload = b"x" * 500
    sha = hashlib.sha256(payload).hexdigest()
    _install_fake_get(monkeypatch, _release_json(sha256=sha), payload)

    info = mr.fetch_latest_release()
    assert info["version"] == "99.0"
    assert info["download_url"] == "https://example.com/MultiRoblox.exe"
    assert info["sha256"] == sha


def test_fetch_latest_release_returns_none_without_a_repo_configured(monkeypatch):
    monkeypatch.setattr(mr, "GITHUB_REPO", "")
    assert mr.fetch_latest_release() is None


def test_check_for_update_returns_none_when_already_current(monkeypatch):
    monkeypatch.setattr(mr, "GITHUB_REPO", "some/repo")
    monkeypatch.setattr(mr, "APP_VERSION", "99.0")
    _install_fake_get(monkeypatch, _release_json(tag="v99.0"))
    assert mr.check_for_update() is None


def test_download_verified_update_writes_the_real_bytes_and_matches_hash(
        monkeypatch, tmp_path):
    monkeypatch.setattr(mr, "GITHUB_REPO", "some/repo")
    payload = b"totally real exe bytes" * 10000  # exercise multiple chunks
    sha = hashlib.sha256(payload).hexdigest()
    _install_fake_get(monkeypatch, _release_json(sha256=sha), payload)

    seen_progress = []
    path, error = mr.download_verified_update(
        str(tmp_path), progress_cb=lambda done, total: seen_progress.append(done))

    assert error is None
    assert path is not None
    assert os.path.exists(path)
    with open(path, "rb") as f:
        assert f.read() == payload
    assert seen_progress and seen_progress[-1] == len(payload)


def test_a_hash_mismatch_deletes_the_file_and_reports_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(mr, "GITHUB_REPO", "some/repo")
    payload = b"some bytes"
    wrong_sha = "0" * 64
    _install_fake_get(monkeypatch, _release_json(sha256=wrong_sha), payload)

    path, error = mr.download_verified_update(str(tmp_path))

    assert path is None
    assert "didn't match" in error
    assert os.listdir(str(tmp_path)) == []


def test_no_matching_asset_fails_without_downloading_anything(monkeypatch, tmp_path):
    monkeypatch.setattr(mr, "GITHUB_REPO", "some/repo")
    _install_fake_get(monkeypatch, _release_json(with_asset=False, sha256="a" * 64))

    path, error = mr.download_verified_update(str(tmp_path))

    assert path is None
    assert "no MultiRoblox.exe" in error
    assert os.listdir(str(tmp_path)) == []


def test_missing_sha256_in_release_notes_refuses_rather_than_download_unverified(
        monkeypatch, tmp_path):
    monkeypatch.setattr(mr, "GITHUB_REPO", "some/repo")
    _install_fake_get(monkeypatch, _release_json(sha256=None))

    path, error = mr.download_verified_update(str(tmp_path))

    assert path is None
    assert "SHA-256" in error
    assert os.listdir(str(tmp_path)) == []


def test_already_current_version_does_not_download(monkeypatch, tmp_path):
    monkeypatch.setattr(mr, "GITHUB_REPO", "some/repo")
    monkeypatch.setattr(mr, "APP_VERSION", "99.0")
    _install_fake_get(monkeypatch, _release_json(tag="v99.0", sha256="a" * 64))

    path, error = mr.download_verified_update(str(tmp_path))

    assert path is None
    assert "already have" in error
