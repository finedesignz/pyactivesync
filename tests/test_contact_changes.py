from __future__ import annotations

from typing import cast
from unittest.mock import patch

import pytest

from pyactivesync import Client, Contact, ContactChange
from pyactivesync._wbxml import Node, WBXMLReader, WBXMLWriter, find, text_of, wtag


def _client() -> Client:
    client = Client("example.invalid", "user", "password", device_id="ContactMutationTest")
    client._provisioned = True
    return client


def _child(node: Node, name: str) -> Node:
    match = next((child for child in node[2] if child[0] == name), None)
    assert match is not None, f"missing direct child {name} of {node[0]}"
    return cast(Node, match)


def _response() -> bytes:
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
                                children=[
                                    wtag(
                                        "AirSync",
                                        "Change",
                                        children=[
                                            wtag("AirSync", "ServerId", text="b"),
                                            wtag("AirSync", "Status", text="8"),
                                        ],
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    return w.render()


def test_apply_contact_changes_builds_all_mutations_and_parses_statuses() -> None:
    client = _client()
    changes = [
        ContactChange("a", contact=Contact(first_name="Ada", job_title="Mathematician")),
        ContactChange("b", contact=Contact(mobile_phone_number="+1-555-0100")),
        ContactChange("c", delete=True),
    ]
    with patch.object(client, "_post", return_value=_response()) as post:
        result = client.apply_contact_changes("9", "1", changes, deletes_as_moves=False)

    assert post.call_args.args[0] == "Sync"
    assert post.call_args.kwargs == {}
    nodes = WBXMLReader(post.call_args.args[1]).parse()
    root = find(nodes, "AirSync.Sync")
    assert root is not None
    collection = _child(_child(root, "AirSync.Collections"), "AirSync.Collection")
    assert text_of(_child(collection, "AirSync.SyncKey")) == "1"
    assert text_of(_child(collection, "AirSync.CollectionId")) == "9"
    assert text_of(_child(collection, "AirSync.DeletesAsMoves")) == "0"
    assert text_of(_child(collection, "AirSync.GetChanges")) == "0"
    commands = _child(collection, "AirSync.Commands")
    command_nodes = [cast(Node, node) for node in commands[2]]
    assert [node[0] for node in command_nodes] == ["AirSync.Change", "AirSync.Change", "AirSync.Delete"]

    first_data = _child(command_nodes[0], "AirSync.ApplicationData")
    assert text_of(_child(first_data, "Contacts.FirstName")) == "Ada"
    assert text_of(_child(first_data, "Contacts.JobTitle")) == "Mathematician"

    second_data = _child(command_nodes[1], "AirSync.ApplicationData")
    assert text_of(_child(second_data, "Contacts.MobilePhoneNumber")) == "+1-555-0100"
    assert find(second_data[2], "Contacts.FirstName") is None
    assert text_of(_child(command_nodes[2], "AirSync.ServerId")) == "c"

    assert result.sync_key == "2"
    assert result.statuses == {"a": "1", "b": "8", "c": "1"}


@pytest.mark.parametrize(
    ("folder_id", "sync_key", "changes", "message"),
    [
        ("", "1", [ContactChange("a", contact=Contact(first_name="Ada"))], "folder_id"),
        ("9", "0", [ContactChange("a", contact=Contact(first_name="Ada"))], "sync_key"),
        ("9", "1", [], "at least one"),
        ("9", "1", [ContactChange("", contact=Contact(first_name="Ada"))], "server_id"),
        ("9", "1", [ContactChange("a")], "no mutation"),
        (
            "9",
            "1",
            [ContactChange("a", contact=Contact(first_name="Ada"), delete=True)],
            "cannot be combined",
        ),
        (
            "9",
            "1",
            [ContactChange("a", contact=Contact(first_name="Ada")), ContactChange("a", contact=Contact(last_name="L"))],
            "duplicate",
        ),
        ("9", "1", [ContactChange("a", contact=Contact())], "no fields set"),
    ],
)
def test_apply_contact_changes_validates_input(
    folder_id: str, sync_key: str, changes: list[ContactChange], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _client().apply_contact_changes(folder_id, sync_key, changes)
