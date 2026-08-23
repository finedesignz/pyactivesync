"""Integration tests against a real EAS server.

Skipped (not failed) unless PYACTIVESYNC_TEST_SERVER / PYACTIVESYNC_TEST_USER /
PYACTIVESYNC_TEST_PASSWORD are set, so `pytest` stays green on a plain checkout
and in default CI. Run manually against a real account before a release:

    PYACTIVESYNC_TEST_SERVER=mail.example.com \\
    PYACTIVESYNC_TEST_USER='CORP\\jdoe' \\
    PYACTIVESYNC_TEST_PASSWORD=... \\
    pytest tests/test_client_live.py

Mutating tests only ever create/rename/delete objects prefixed
`pyactivesync-test-` that they create themselves; a session-scoped fixture
(`preexisting_folder_ids`) asserts the pre-existing folder set is
unchanged at the end of the run.
"""
from __future__ import annotations

import time
import uuid
from email.message import EmailMessage

import pytest

from pyactivesync import BodyType, Client, EmailChange, FetchedItem, FolderType, OofState
from pyactivesync.exceptions import StatusError


def test_provision_returns_policy_key(live_client: Client) -> None:
    key = live_client.provision()
    assert key


def test_list_folders_includes_inbox(live_client: Client) -> None:
    folders = live_client.list_folders()
    assert any(f.type == FolderType.INBOX for f in folders)


def test_sync_folder_bootstrap_then_delta(live_client: Client) -> None:
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    bootstrap = live_client.sync_folder(inbox.id)
    assert bootstrap.sync_key != "0"
    delta = live_client.sync_folder(inbox.id, sync_key=bootstrap.sync_key)
    assert delta.sync_key


def test_get_item_estimate(live_client: Client) -> None:
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    bootstrap = live_client.sync_folder(inbox.id)
    estimate = live_client.get_item_estimate(inbox.id, bootstrap.sync_key)
    assert estimate >= 0


def test_fetch_existing_item_and_attachment_read_only(live_client: Client) -> None:
    """Fetch an existing message and, when one is present in the sync window,
    one of its attachments. ItemOperations Fetch does not mutate the item.
    """
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    result = live_client.sync_folder(inbox.id)
    result = live_client.sync_folder(inbox.id, sync_key=result.sync_key, window_size=100)
    items = result.added + result.changed
    if not items:
        pytest.skip("Inbox sync window contained no fetchable items")

    first_properties = live_client.fetch_item(inbox.id, items[0].server_id)
    assert isinstance(first_properties, FetchedItem)
    mime_item = live_client.fetch_item(inbox.id, items[0].server_id, body_type=BodyType.MIME)
    assert mime_item.body is not None
    assert mime_item.body.type == BodyType.MIME
    assert isinstance(mime_item.body.data, bytes)

    for item in items:
        properties = live_client.fetch_item(inbox.id, item.server_id)
        if properties.attachments:
            assert isinstance(live_client.fetch_attachment(properties.attachments[0].file_reference), bytes)
            return
    pytest.skip("Inbox sync window contained no item with an attachment")


def test_resolve_recipients_self(live_client: Client) -> None:
    recipients = live_client.resolve_recipients(live_client.user)
    assert isinstance(recipients, list)


def test_folder_lifecycle_only_touches_its_own_folder(live_client: Client, preexisting_folder_ids: set[str]) -> None:
    """FolderCreate -> FolderUpdate -> FolderDelete against a throwaway
    folder only; asserts the pre-existing folder set is untouched."""
    name = f"pyactivesync-test-{uuid.uuid4().hex[:8]}"
    folder = live_client.create_folder(name, parent_id="0", type=FolderType.USER_GENERIC)
    assert folder.id not in preexisting_folder_ids

    renamed = f"{name}-renamed"
    live_client.update_folder(folder.id, renamed, parent_id="0")

    live_client.delete_folder(folder.id)

    folders_after = {f.id for f in live_client.list_folders()}
    assert preexisting_folder_ids <= folders_after
    assert folder.id not in folders_after


def test_send_mail_move_mutate_and_fetch_attachment(live_client: Client, preexisting_folder_ids: set[str]) -> None:
    """Exercise item writes only against a message and folder created here."""
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    marker = f"pyactivesync-test-{uuid.uuid4().hex[:8]}"

    msg = EmailMessage()
    msg["To"] = live_client.user
    msg["Subject"] = marker
    msg.set_content("throwaway message for pyactivesync integration tests")
    msg.add_attachment(b"hello from pyactivesync", maintype="application", subtype="octet-stream", filename="test.txt")
    msg.add_attachment(b"second attachment", maintype="application", subtype="octet-stream", filename="second.bin")
    live_client.send_mail(msg)

    item_id = None
    sync_key = "0"
    for _ in range(10):
        result = live_client.sync_folder(inbox.id, sync_key=sync_key, window_size=25)
        sync_key = result.sync_key
        match = next((i for i in result.added if i.fields.get("Email.Subject") == marker), None)
        if match:
            item_id = match.server_id
            break
        time.sleep(3)
    assert item_id, f"message {marker!r} never showed up via Sync"

    fetched = live_client.fetch_item(inbox.id, item_id)
    assert fetched.body is not None

    folder_name = f"pyactivesync-test-{uuid.uuid4().hex[:8]}"
    test_folder = live_client.create_folder(folder_name, parent_id="0", type=FolderType.USER_GENERIC)
    assert test_folder.id not in preexisting_folder_ids

    new_id = live_client.move_item(item_id, inbox.id, test_folder.id)
    assert new_id

    props = live_client.fetch_item(test_folder.id, new_id)
    attachments = {
        attachment.display_name: live_client.fetch_attachment(attachment.file_reference)
        for attachment in props.attachments
    }
    assert attachments["test.txt"] == b"hello from pyactivesync"
    assert attachments["second.bin"] == b"second attachment"

    bootstrap = live_client.sync_folder(test_folder.id)
    synced = live_client.sync_folder(test_folder.id, sync_key=bootstrap.sync_key)
    assert any(item.server_id == new_id for item in synced.added + synced.changed)

    changed = live_client.apply_email_changes(
        test_folder.id,
        synced.sync_key,
        [EmailChange(new_id, read=True, flagged=True)],
    )
    assert changed.statuses[new_id] == "1"
    props = live_client.fetch_item(test_folder.id, new_id)
    assert props.fields.get("Email.Read") == "1"
    assert props.fields.get("Email.Status") == "2"

    changed = live_client.apply_email_changes(
        test_folder.id,
        changed.sync_key,
        [EmailChange(new_id, read=False, flagged=False)],
    )
    assert changed.statuses[new_id] == "1"
    props = live_client.fetch_item(test_folder.id, new_id)
    assert props.fields.get("Email.Read") == "0"
    assert props.fields.get("Email.Status") in {None, "0"}

    deleted = live_client.apply_email_changes(
        test_folder.id,
        changed.sync_key,
        [EmailChange(new_id, delete=True)],
        deletes_as_moves=False,
    )
    assert deleted.statuses[new_id] == "1"
    with pytest.raises(StatusError):
        live_client.fetch_item(test_folder.id, new_id)

    live_client.delete_folder(test_folder.id)
    folders_after = {f.id for f in live_client.list_folders()}
    assert preexisting_folder_ids <= folders_after


def test_create_email_draft_only_touches_its_own_item(live_client: Client) -> None:
    """Create a MIME draft through Sync Add, verify it, then delete it."""
    drafts = next(f for f in live_client.list_folders() if f.type == FolderType.DRAFTS)
    bootstrap = live_client.sync_folder(drafts.id)
    marker = f"pyactivesync-test-{uuid.uuid4().hex[:8]}"

    message = EmailMessage()
    message["To"] = live_client.user
    message["Subject"] = marker
    message.set_content("throwaway draft for pyactivesync integration tests")
    message.add_attachment(b"draft attachment", maintype="application", subtype="octet-stream", filename="draft.bin")

    created = live_client.create_email_draft(
        drafts.id,
        bootstrap.sync_key,
        message,
        read=True,
        flagged=True,
        client_id=marker,
    )
    assert created.status == "1"
    assert created.server_id
    try:
        properties = live_client.fetch_item(drafts.id, created.server_id)
        assert properties.fields.get("Email.Subject") == marker
        assert properties.fields.get("Email.Read") == "1"
        assert properties.fields.get("Email.Status") == "2"
        assert properties.attachments
        assert live_client.fetch_attachment(properties.attachments[0].file_reference) == b"draft attachment"
    finally:
        live_client.apply_email_changes(
            drafts.id,
            created.sync_key,
            [EmailChange(created.server_id, delete=True)],
            deletes_as_moves=False,
        )


def test_search_gal_for_self(live_client: Client) -> None:
    try:
        results = live_client.search_gal(live_client.user)
    except StatusError:
        pytest.skip("GAL search not supported/enabled on this server")
    assert isinstance(results, list)


def test_search_mailbox_structured_read_only(live_client: Client) -> None:
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    results = live_client.search_mailbox(
        inbox.id,
        date_received_after="2020-01-01T00:00:00.000Z",
        max_results=10,
    )
    assert isinstance(results, list)


def test_find_mailbox_free_text_read_only(live_client: Client) -> None:
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    result = live_client.find_mailbox("meeting", folder_id=inbox.id)
    assert result.status == "1"
    assert isinstance(result.items, list)


def test_search_mailbox_free_text_read_only(live_client: Client) -> None:
    """search_mailbox(free_text=...) is rerouted internally to the Find
    command -- Search's own FreeText condition is a confirmed server-side
    bug (Store.Status=110) -- and adapted back to search_mailbox's normal
    list[dict[str, str]] shape."""
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    results = live_client.search_mailbox(inbox.id, free_text="meeting", max_results=10)
    assert isinstance(results, list)


def test_search_mailbox_requires_exactly_one_condition(live_client: Client) -> None:
    inbox = next(f for f in live_client.list_folders() if f.type == FolderType.INBOX)
    with pytest.raises(ValueError):
        live_client.search_mailbox(inbox.id)
    with pytest.raises(ValueError):
        live_client.search_mailbox(inbox.id, date_received_after="2020-01-01T00:00:00.000Z", free_text="meeting")


def test_find_gal_read_only(live_client: Client) -> None:
    result = live_client.find_gal("Mart")
    assert result.status == "1"
    assert isinstance(result.items, list)


def test_ping_returns_a_status(live_client: Client) -> None:
    folders = live_client.list_folders()
    inbox = next(f for f in folders if f.type == FolderType.INBOX)
    drafts = next(f for f in folders if f.type == FolderType.DRAFTS)
    result = live_client.ping([inbox.id, drafts.id], timeout=10)
    assert result.status


def test_get_oof_returns_current_state(live_client: Client) -> None:
    try:
        oof = live_client.get_oof()
    except StatusError:
        pytest.skip("Settings/Oof not supported/enabled on this server")
    assert isinstance(oof.state, OofState)
