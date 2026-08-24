from __future__ import annotations

from unittest.mock import patch

from pyactivesync import Client
from pyactivesync._wbxml import WBXMLWriter, wtag


def _client() -> Client:
    client = Client("example.invalid", "user", "password", device_id="SyncTest")
    client._provisioned = True
    return client


def test_sync_folder_bootstrap_returns_new_key() -> None:
    w = WBXMLWriter()
    w.tag(
        "AirSync",
        "Sync",
        children=[wtag("AirSync", "Collections", children=[
            wtag("AirSync", "Collection", children=[
                wtag("AirSync", "SyncKey", text="1"),
                wtag("AirSync", "CollectionId", text="9"),
                wtag("AirSync", "Status", text="1"),
            ]),
        ])],
    )
    client = _client()
    with patch.object(client, "_post", return_value=w.render()):
        result = client.sync_folder("9", "0")
    assert result.sync_key == "1"
    assert result.added == []
    assert result.more_available is False


def test_sync_folder_empty_response_body_is_treated_as_no_changes() -> None:
    """Some servers send an empty body for a collection with nothing to report

    (observed live against Exchange for an empty folder) rather than an
    envelope that echoes the unchanged SyncKey. This must not crash the
    WBXML parser -- the collection simply has no changes.
    """
    client = _client()
    with patch.object(client, "_post", return_value=b""):
        result = client.sync_folder("9", "5", window_size=100)
    assert result.sync_key == "5"
    assert result.added == []
    assert result.changed == []
    assert result.deleted == []
    assert result.more_available is False
