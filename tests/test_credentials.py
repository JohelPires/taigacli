from __future__ import annotations

import json
import sys

import pytest

from taigacli import credentials


class FakeKeyring:
    """In-memory stand-in for the keyring module."""

    def __init__(self):
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def get_password(self, service, username):
        return self.store.get((service, username))

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise KeyError((service, username))
        del self.store[(service, username)]


@pytest.fixture
def fake_kr(monkeypatch):
    kr = FakeKeyring()
    monkeypatch.setattr(credentials, "_keyring", lambda: kr)
    return kr


def test_save_load_roundtrip(fake_kr):
    assert credentials.save("https://a/api/v1", "alice", "pw") is True
    assert credentials.load("https://a/api/v1") == ("alice", "pw")
    # stored as a JSON blob so renewal needs only the API URL
    blob = json.loads(fake_kr.store[(credentials.SERVICE, "https://a/api/v1")])
    assert set(blob) == {"username", "password"}


def test_load_missing_returns_none(fake_kr):
    assert credentials.load("https://nothing/api/v1") is None


def test_keyring_unavailable(fake_kr, monkeypatch):
    monkeypatch.setattr(credentials, "_keyring", lambda: None)
    assert credentials.available() is False
    assert credentials.save("https://a/api/v1", "u", "p") is False
    assert credentials.load("https://a/api/v1") is None
    assert credentials.forget("https://a/api/v1") is False


def test_forget_removes_entry(fake_kr):
    credentials.save("https://a/api/v1", "alice", "pw")
    assert credentials.forget("https://a/api/v1") is True
    assert credentials.load("https://a/api/v1") is None
    assert credentials.forget("https://a/api/v1") is False


def test_corrupt_entry_degrades(fake_kr):
    fake_kr.store[(credentials.SERVICE, "https://a/api/v1")] = "not json"
    assert credentials.load("https://a/api/v1") is None


def test_corrupt_secret_forget_still_clears(fake_kr):
    fake_kr.store[(credentials.SERVICE, "https://a/api/v1")] = "not json"
    assert credentials.forget("https://a/api/v1") is True


def test_missing_keyring_module(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", None)  # import raises ImportError
    assert credentials.load("https://a/api/v1") is None
    assert credentials.available() is False
