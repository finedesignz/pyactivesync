from __future__ import annotations

from typing import cast
from unittest.mock import patch

import pytest

from pyactivesync import Client, Contact
from pyactivesync._wbxml import Node, WBXMLReader, WBXMLWriter, find, text_of, wtag
from pyactivesync.exceptions import ProtocolError, StatusError


def _client() -> Client:
    client = Client("example.invalid", "user", "password", device_id="ContactAddTest")
    client._provisioned = True
    return client


def _child(node: Node, name: str) -> Node:
    match = next((child for child in node[2] if child[0] == name), None)
    assert match is not None, f"missing direct child {name} of {node[0]}"
    return cast(Node, match)


def _response(*, item_status: str = "1", server_id: str | None = "9:1") -> bytes:
    add_children = [
        wtag("AirSync", "ClientId", text="local-1"),
        wtag("AirSync", "Status", text=item_status),
    ]
    if server_id is not None:
        add_children.insert(1, wtag("AirSync", "ServerId", text=server_id))
    w = WBXMLWriter()
    w.tag(
        "AirSync",
        "Sync",
        children=[
            wtag(
                "AirSync",
                "Collections",
                children=[
                    wtag(
                        "AirSync",
                        "Collection",
                        children=[
                            wtag("AirSync", "SyncKey", text="2"),
                            wtag("AirSync", "CollectionId", text="9"),
                            wtag("AirSync", "Status", text="1"),
                            wtag(
                                "AirSync",
                                "Responses",
                                children=[wtag("AirSync", "Add", children=add_children)],
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    return w.render()


def _contact() -> Contact:
    return Contact(
        first_name="Ada",
        last_name="Lovelace",
        email1_address="ada@example.com",
        company_name="Analytical Engines Ltd",
        categories=("VIP", "Math"),
    )


def test_create_contact_builds_add_and_parses_result() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response()) as post:
        result = client.create_contact("9", "1", _contact(), client_id="local-1")

    assert post.call_args.args[0] == "Sync"
    assert post.call_args.kwargs == {}
    nodes = WBXMLReader(post.call_args.args[1]).parse()
    root = find(nodes, "AirSync.Sync")
    assert root is not None
    collection = _child(_child(root, "AirSync.Collections"), "AirSync.Collection")
    assert text_of(_child(collection, "AirSync.SyncKey")) == "1"
    assert text_of(_child(collection, "AirSync.CollectionId")) == "9"
    assert text_of(_child(collection, "AirSync.GetChanges")) == "0"
    add = _child(_child(collection, "AirSync.Commands"), "AirSync.Add")
    assert text_of(_child(add, "AirSync.ClientId")) == "local-1"
    appdata = _child(add, "AirSync.ApplicationData")
    assert text_of(_child(appdata, "Contacts.FirstName")) == "Ada"
    assert text_of(_child(appdata, "Contacts.LastName")) == "Lovelace"
    assert text_of(_child(appdata, "Contacts.Email1Address")) == "ada@example.com"
    assert text_of(_child(appdata, "Contacts.CompanyName")) == "Analytical Engines Ltd"
    categories = _child(appdata, "Contacts.Categories")
    category_nodes = [cast(Node, node) for node in categories[2]]
    assert [text_of(node) for node in category_nodes] == ["VIP", "Math"]

    assert result.sync_key == "2"
    assert result.client_id == "local-1"
    assert result.status == "1"
    assert result.server_id == "9:1"


def test_create_contact_returns_item_failure_status() -> None:
    client = _client()
    with patch.object(client, "_post", return_value=_response(item_status="6", server_id=None)):
        result = client.create_contact("9", "1", _contact(), client_id="local-1")

    assert result.sync_key == "2"
    assert result.status == "6"
    assert result.server_id is None


@pytest.mark.parametrize(
    ("folder_id", "sync_key", "client_id", "message"),
    [
        ("", "1", "local-1", "folder_id"),
        ("9", "0", "local-1", "sync_key"),
        ("9", "1", "", "client_id"),
    ],
)
def test_create_contact_validates_input(folder_id: str, sync_key: str, client_id: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _client().create_contact(folder_id, sync_key, _contact(), client_id=client_id)


def test_create_contact_rejects_non_contact() -> None:
    with pytest.raises(TypeError, match="Contact"):
        _client().create_contact("9", "1", cast(Contact, object()))


def test_create_contact_requires_at_least_one_field() -> None:
    with pytest.raises(ValueError, match="no fields set"):
        _client().create_contact("9", "1", Contact())


def test_create_contact_raises_collection_status_error() -> None:
    w = WBXMLWriter()
    w.tag(
        "AirSync",
        "Sync",
        children=[
            wtag(
                "AirSync",
                "Collections",
                children=[
                    wtag(
                        "AirSync",
                        "Collection",
                        children=[wtag("AirSync", "Status", text="3")],
                    )
                ],
            )
        ],
    )
    client = _client()
    with patch.object(client, "_post", return_value=w.render()), pytest.raises(StatusError) as exc:
        client.create_contact("9", "1", _contact(), client_id="local-1")
    assert "Status=3" in str(exc.value)


def test_create_contact_requires_correlated_item_response() -> None:
    response = _response().replace(b"local-1", b"other--")
    client = _client()
    with patch.object(client, "_post", return_value=response), pytest.raises(ProtocolError, match="ClientId"):
        client.create_contact("9", "1", _contact(), client_id="local-1")
