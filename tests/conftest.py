import pytest


@pytest.fixture(autouse=True)
def _no_keyring(monkeypatch):
    """Keep tests offline of the real OS keyring: `credentials._keyring` -> None."""
    monkeypatch.setattr("taigacli.credentials._keyring", lambda: None)
