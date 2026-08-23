# pyactivesync

A Python client library exclusively for Exchange ActiveSync (EAS) 16.1, implementing
enough of [MS-ASCMD] (the command protocol) and [MS-ASWBXML] (the binary
XML encoding) to talk to a real Exchange server: folder listing, mail
sync, item/attachment fetch, sending mail, folder management, moving
items, directory search, and push notifications via `Ping`.

[MS-ASCMD]: https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-ascmd/
[MS-ASWBXML]: https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-aswbxml/

## Protocol version

Pyactivesync targets **EAS 16.1 exclusively**. Every request carries
`MS-ASProtocolVersion: 16.1`; the version is not configurable and the
library does not negotiate or fall back to older protocol versions. The
server must advertise EAS 16.1 support.

## Install

```
pip install pyactivesync
```

## Usage

```python
from email.message import EmailMessage
from pyactivesync import Client, EmailChange, FolderType, BodyType

with Client(
    server="mail.example.com",
    username=r"CORP\jdoe",       # NTLM-style domain\user, or a plain email -- both work
    password="...",
    device_id="MyApp01",          # caller-provided; persist it yourself for a stable
                                    # device identity across runs -- pyactivesync doesn't
                                    # persist anything to disk on its own
) as client:
    folders = client.list_folders()
    inbox = next(f for f in folders if f.type == FolderType.INBOX)
    drafts = next(f for f in folders if f.type == FolderType.DRAFTS)

    result = client.sync_folder(inbox.id)                              # bootstrap
    result = client.sync_folder(inbox.id, sync_key=result.sync_key)     # Add/Change/Delete

    ping = client.ping([inbox.id, drafts.id], heartbeat=60)
    print(ping.changed_folder_ids)

    for item in result.added:
        print(item.fields.get("Email.Subject"))
        fetched = client.fetch_item(inbox.id, item.server_id, body_type=BodyType.HTML)
        print(fetched.body.data if fetched.body else None)
        for attachment in fetched.attachments:
            data = client.fetch_attachment(attachment.file_reference)

    if result.added:
        # Mutations consume and advance the folder's SyncKey.
        changes = client.apply_email_changes(
            inbox.id,
            result.sync_key,
            [EmailChange(result.added[0].server_id, read=True, flagged=True)],
        )

    msg = EmailMessage()
    msg["To"] = "someone@example.com"
    msg["Subject"] = "hello from pyactivesync"
    msg.set_content("plain text body")
    client.send_mail(msg)

    # Sync Add is EAS 16.1's draft-creation operation. It consumes the
    # Drafts collection's current SyncKey and returns the next key + ServerId.
    draft_sync = client.sync_folder(drafts.id)
    created = client.create_email_draft(drafts.id, draft_sync.sync_key, msg)
    assert created.status == "1" and created.server_id
```

Use `read=False` to mark an item unread, `flagged=False` to clear its
follow-up flag, and `delete=True` to delete it. Pass each returned
`EmailChangesResult.sync_key` into the next mutation or sync request for that
folder.

`Client` is a context manager wrapping one `requests.Session` -- EAS is
stateless HTTP (an auth header plus a `PolicyKey` header), so unlike an
IMAP connection there's no server-side session to tear down; `__exit__`
just closes the HTTP session. `provision()` (the device policy handshake)
is called lazily on first use if you don't call it explicitly.

Folder and item ids are plain strings (`"9"`, `"9:1"`), matching EAS's
own `ServerId` format exactly -- there's no synthetic id layer to keep in
sync with a local cache.

## Command coverage

| Command | Client method |
|---|---|
| `Provision` | `Client.provision()` (also called lazily) |
| `FolderSync` | `Client.list_folders()` |
| `Sync` | `Client.sync_folder()` |
| `Sync` Add | `Client.create_email_draft()` (draft email only) |
| `Sync` item mutation | `Client.apply_email_changes()` (read/flag/delete) |
| `GetItemEstimate` | `Client.get_item_estimate()` |
| `ItemOperations` Fetch (item/body metadata) | `Client.fetch_item()` |
| `ItemOperations` Fetch (attachment) | `Client.fetch_attachment()` |
| `SendMail` | `Client.send_mail()` |
| `FolderCreate`/`FolderUpdate`/`FolderDelete` | `Client.create_folder()`/`update_folder()`/`delete_folder()` |
| `MoveItems` | `Client.move_item()` |
| `Ping` | `Client.ping()` |
| `ResolveRecipients` | `Client.resolve_recipients()` |
| `Search` (GAL) | `Client.search_gal()` |
| `Search` (Mailbox, structured or free text via `Find`) | `Client.search_mailbox()` |
| `Find` (GAL/Mailbox free text) | `Client.find_gal()`/`Client.find_mailbox()` |
| `Settings` (Oof get/set) | `Client.get_oof()`/`set_oof()` |

**Not implemented**: `MeetingResponse`, `ValidateCert`, `SmartForward`/`SmartReply`.
Documented as unimplemented, not silently missing.

**Non-goals**: an EAS *server*; Autodiscover (pass a server hostname
directly); Calendar/Contacts *write* operations (read via `Sync` is
supported); NTLM auth (Basic auth only -- `requests` doesn't do NTLM
without an extra dependency); credential storage of any kind (that's the
caller's business).

EAS 16.1 supports client-originated `Sync` Add for draft email only.
`create_email_draft()` therefore expects the Drafts collection and stores the
stdlib message as a MIME body, including attachments. It does not provide an
IMAP-style arbitrary-folder `APPEND`: Exchange reports item status `6` for a
non-draft email addition. The result always includes the advanced collection
`SyncKey`, the caller-supplied or generated `ClientId`, and the per-item
status; successful additions also include the assigned `ServerId`.
Live EAS 16.1 testing confirmed that Exchange accepts this MIME draft path,
including attachment round-trips and read/follow-up flag state.

`fetch_item()` returns a typed `FetchedItem`, not a flattened property map.
Its ordered `bodies` and `attachments` lists preserve repeated EAS containers;
`body` is a convenience alias for the first body. MIME body data is returned
as bytes, and each attachment retains its own file reference, display name,
size, method, content identifiers, and inline state. Other scalar properties
remain available through `FetchedItem.fields`.

`send_mail()` accepts an optional `client_id=` of 1 to 40 characters. When it
is omitted, pyactivesync generates a UUID as before. A bridge can persist and
supply this identifier before submitting a message, but caller control does
not by itself make an ambiguous SendMail safe to retry: duplicate-ClientId
behavior is server-dependent, and pyactivesync never automatically retries
this non-idempotent command.

A `FreeText` condition on the `Search` command itself is known to fail
against real Exchange servers with `Store.Status=110`, a server-side bug
in EAS's `Search` handling rather than a WBXML encoding issue (confirmed
by cross-checking the same mailbox's content index through an unrelated
protocol, which returns correct results for the same query; re-confirmed
live as of 2026-08-23 -- still broken server-side). `search_mailbox()`
accepts a `free_text=` parameter anyway: when given, it transparently
reroutes the request through the EAS 16.1 `Find` command instead (see
below), which implements full-text search correctly, and adapts the
result back to `search_mailbox()`'s normal `list[dict[str, str]]` shape.
Pass exactly one of `date_received_after=` or `free_text=`.

EAS 16.1's separate `Find` command is also available directly through
`find_mailbox()` and `find_gal()`. Both return a `FindResult` containing
the server's status, range, actual number of returned items, reusable
search id, and flattened result properties. Call `find_mailbox()` directly
instead of `search_mailbox(free_text=...)` when you need pagination
(`range_start=`/`search_id=`) or the raw `FindResult`. `FindResult.total`
is computed from the returned results rather than trusting the server's
advisory `Find:Total` value.

## Development

```
pip install -e '.[dev]'
pytest
ruff check .
mypy pyactivesync tests
```

Unit tests (WBXML codec against golden byte fixtures, codepage table
sanity checks) require no network and run in CI on every push. Live
integration tests in `tests/test_client_live.py` are skipped unless
`PYACTIVESYNC_TEST_SERVER`, `PYACTIVESYNC_TEST_USER`, and `PYACTIVESYNC_TEST_PASSWORD` are
set, and only ever create/rename/delete objects they create themselves --
pre-existing folders and items are never touched.

## License

MIT
