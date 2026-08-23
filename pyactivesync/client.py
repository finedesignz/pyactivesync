"""EAS client: one method per MS-ASCMD command, WBXML in and out."""
from __future__ import annotations

import base64
import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from email.message import Message
from types import TracebackType
from typing import overload

from ._http import Transport
from ._mime import to_7bit_crlf_text, to_crlf_bytes
from ._wbxml import Node, NodeBuilder, WBXMLReader, WBXMLWriter, find, find_all, leaves, opaque_of, text_of, wtag
from .exceptions import ProtocolError, ProvisionError, StatusError
from .models import (
    AttachmentInfo,
    BodyType,
    Contact,
    ContactAddResult,
    ContactChange,
    ContactChangesResult,
    EmailAddResult,
    EmailChange,
    EmailChangesResult,
    FetchedItem,
    FindItem,
    FindResult,
    Folder,
    FolderType,
    GalEntry,
    ItemBody,
    OofMessage,
    OofSettings,
    OofState,
    PingResult,
    Recipient,
    SyncItem,
    SyncResult,
)

# Contact dataclass field name -> Contacts codepage tag name. Token values
# are taken verbatim from the official MS-ASWBXML spec (code page 1).
_CONTACT_FIELD_TAGS: dict[str, str] = {
    "first_name": "FirstName",
    "middle_name": "MiddleName",
    "last_name": "LastName",
    "suffix": "Suffix",
    "title": "Title",
    "job_title": "JobTitle",
    "file_as": "FileAs",
    "company_name": "CompanyName",
    "department": "Department",
    "office_location": "OfficeLocation",
    "email1_address": "Email1Address",
    "email2_address": "Email2Address",
    "email3_address": "Email3Address",
    "home_phone_number": "HomePhoneNumber",
    "home2_phone_number": "Home2PhoneNumber",
    "business_phone_number": "BusinessPhoneNumber",
    "business2_phone_number": "Business2PhoneNumber",
    "mobile_phone_number": "MobilePhoneNumber",
    "business_fax_number": "BusinessFaxNumber",
    "home_fax_number": "HomeFaxNumber",
    "pager_number": "PagerNumber",
    "car_phone_number": "CarPhoneNumber",
    "radio_phone_number": "RadioPhoneNumber",
    "assistant_name": "AssistantName",
    "assistant_phone_number": "AssistantPhoneNumber",
    "business_address_street": "BusinessAddressStreet",
    "business_address_city": "BusinessAddressCity",
    "business_address_state": "BusinessAddressState",
    "business_address_postal_code": "BusinessAddressPostalCode",
    "business_address_country": "BusinessAddressCountry",
    "home_address_street": "HomeAddressStreet",
    "home_address_city": "HomeAddressCity",
    "home_address_state": "HomeAddressState",
    "home_address_postal_code": "HomeAddressPostalCode",
    "home_address_country": "HomeAddressCountry",
    "other_address_street": "OtherAddressStreet",
    "other_address_city": "OtherAddressCity",
    "other_address_state": "OtherAddressState",
    "other_address_postal_code": "OtherAddressPostalCode",
    "other_address_country": "OtherAddressCountry",
    "web_page": "WebPage",
    "spouse": "Spouse",
    "birthday": "Birthday",
    "anniversary": "Anniversary",
}


def _contact_application_data(contact: Contact) -> list[NodeBuilder]:
    children = [
        wtag("Contacts", tag, text=value)
        for field_name, tag in _CONTACT_FIELD_TAGS.items()
        if (value := getattr(contact, field_name)) is not None
    ]
    if contact.categories:
        children.append(
            wtag(
                "Contacts",
                "Categories",
                children=[wtag("Contacts", "Category", text=category) for category in contact.categories],
            )
        )
    return children

_OOF_APPLIES_TO_TAGS = {
    "Internal": "AppliesToInternal",
    "ExternalKnown": "AppliesToExternalKnown",
    "ExternalUnknown": "AppliesToExternalUnknown",
}

_PROVISION_STATUS_MEANINGS = {"165": "DeviceInformationRequired"}
_SENDMAIL_STATUS_MEANINGS = {"101": "InvalidContent"}
_MOVEITEMS_STATUS_MEANINGS = {"1": "InvalidSourceId", "2": "InvalidDestinationId"}


def _direct_find(nodes: list[Node], path: str) -> Node | None:
    return next((node for node in nodes if node[0] == path), None)


def _check_status(command: str, status: str | None, meanings: dict[str, str] | None = None) -> None:
    if status is not None and status != "1":
        raise StatusError(command, status, (meanings or {}).get(status))


def _validate_compose_client_id(client_id: str) -> None:
    """Validate the ComposeMail schema's 1..40-character XML string."""
    if not isinstance(client_id, str):
        raise TypeError("client_id must be a string")
    if not 1 <= len(client_id) <= 40:
        raise ValueError("client_id must contain between 1 and 40 characters")
    if any(
        char not in "\t\n\r"
        and not ("\u0020" <= char <= "\ud7ff")
        and not ("\ue000" <= char <= "\ufffd")
        and not ("\U00010000" <= char <= "\U0010ffff")
        for char in client_id
    ):
        raise ValueError("client_id contains a character that is not valid in XML")


class Client:
    """A stateless-HTTP EAS client wrapping one connection to a single mailbox.

    ``username`` is passed to HTTP Basic auth as-is (NTLM-style
    ``domain\\user`` or a plain email, both work against Basic-auth EAS
    endpoints). ``user`` is the value sent as the ``User`` query parameter
    on every command (the mailbox's SMTP address) -- it defaults to
    ``username`` and only needs to be set separately when the login
    identity and the mailbox's primary SMTP address differ.
    """

    def __init__(
        self,
        server: str,
        username: str,
        password: str,
        *,
        device_id: str,
        user: str | None = None,
        device_type: str = "pyactivesync",
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.user = user or username
        self._transport = Transport(
            server,
            username,
            password,
            device_id=device_id,
            device_type=device_type,
            verify_ssl=verify_ssl,
            timeout=timeout,
        )
        self._provisioned = False

    def __enter__(self) -> Client:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._transport.close()

    def _post(
        self,
        cmd: str,
        wbxml: bytes,
        *,
        extra_params: dict[str, str] | None = None,
        timeout: float | None = None,
        idempotent: bool = False,
    ) -> bytes:
        return self._transport.post(
            cmd, self.user, wbxml, extra_params=extra_params, timeout=timeout, idempotent=idempotent
        )

    def _ensure_provisioned(self) -> None:
        if not self._provisioned:
            self.provision()

    # -- Device provisioning -------------------------------------------------

    def provision(self) -> str:
        """Acknowledge device policy (two round-trips). Returns the granted PolicyKey.

        A bare ``Provision`` request is rejected with ``Status=165``
        (``DeviceInformationRequired``) unless a ``Settings.DeviceInformation``
        block is included on the first request.
        """
        w = WBXMLWriter()
        w.tag(
            "Provision",
            "Provision",
            children=[
                wtag(
                    "Settings",
                    "DeviceInformation",
                    children=[
                        wtag(
                            "Settings",
                            "Set",
                            children=[
                                wtag("Settings", "Model", text="pyactivesync"),
                                wtag("Settings", "FriendlyName", text="pyactivesync client"),
                                wtag("Settings", "OS", text="Linux"),
                                wtag("Settings", "UserAgent", text="pyactivesync/0.1"),
                            ],
                        ),
                    ],
                ),
                wtag(
                    "Provision",
                    "Policies",
                    children=[
                        wtag(
                            "Provision",
                            "Policy",
                            children=[wtag("Provision", "PolicyType", text="MS-EAS-Provisioning-WBXML")],
                        ),
                    ],
                ),
            ],
        )
        resp = self._post("Provision", w.render())
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Provision.Status"))
        _check_status("Provision", status, _PROVISION_STATUS_MEANINGS)
        temp_key = text_of(find(nodes, "Provision.PolicyKey"))
        if not temp_key:
            raise ProvisionError("Provision: no PolicyKey in response")

        w2 = WBXMLWriter()
        w2.tag(
            "Provision",
            "Provision",
            children=[
                wtag(
                    "Provision",
                    "Policies",
                    children=[
                        wtag(
                            "Provision",
                            "Policy",
                            children=[
                                wtag("Provision", "PolicyType", text="MS-EAS-Provisioning-WBXML"),
                                wtag("Provision", "PolicyKey", text=temp_key),
                                wtag("Provision", "Status", text="1"),
                            ],
                        ),
                    ],
                ),
            ],
        )
        resp2 = self._post("Provision", w2.render(), extra_params={"PolicyKey": temp_key})
        nodes2 = WBXMLReader(resp2).parse()
        final_key = text_of(find(nodes2, "Provision.PolicyKey"))
        key = final_key or temp_key
        self._transport.policy_key = key
        self._provisioned = True
        return key

    # -- Folders ---------------------------------------------------------------

    def list_folders(self) -> list[Folder]:
        """Full ``FolderSync`` hierarchy listing."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag("FolderHierarchy", "FolderSync", children=[wtag("FolderHierarchy", "SyncKey", text="0")])
        resp = self._post("FolderSync", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "FolderHierarchy.Status"))
        _check_status("FolderSync", status)
        folders = []
        for _, _, children in find_all(nodes, "FolderHierarchy.Add"):
            server_id = text_of(find(children, "FolderHierarchy.ServerId"))
            parent_id = text_of(find(children, "FolderHierarchy.ParentId"))
            type_ = text_of(find(children, "FolderHierarchy.Type"))
            name = text_of(find(children, "FolderHierarchy.DisplayName"))
            if server_id is None or parent_id is None or type_ is None or name is None:
                raise ProtocolError("FolderSync: incomplete Add entry in response")
            folders.append(Folder(id=server_id, parent_id=parent_id, type=FolderType(int(type_)), name=name))
        return folders

    def _folder_sync_key(self) -> str:
        """Bootstrap ``SyncKey`` for a mutating FolderHierarchy command."""
        w = WBXMLWriter()
        w.tag("FolderHierarchy", "FolderSync", children=[wtag("FolderHierarchy", "SyncKey", text="0")])
        resp = self._post("FolderSync", w.render(), idempotent=True)
        key = text_of(find(WBXMLReader(resp).parse(), "FolderHierarchy.SyncKey"))
        if not key:
            raise ProtocolError("FolderSync: no SyncKey in response")
        return key

    def create_folder(
        self, display_name: str, parent_id: str = "0", type: FolderType = FolderType.USER_GENERIC
    ) -> Folder:
        self._ensure_provisioned()
        sync_key = self._folder_sync_key()
        w = WBXMLWriter()
        w.tag(
            "FolderHierarchy",
            "FolderCreate",
            children=[
                wtag("FolderHierarchy", "SyncKey", text=sync_key),
                wtag("FolderHierarchy", "ParentId", text=parent_id),
                wtag("FolderHierarchy", "DisplayName", text=display_name),
                wtag("FolderHierarchy", "Type", text=str(int(type))),
            ],
        )
        resp = self._post("FolderCreate", w.render())
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "FolderHierarchy.Status"))
        _check_status("FolderCreate", status)
        server_id = text_of(find(nodes, "FolderHierarchy.ServerId"))
        if not server_id:
            raise ProtocolError("FolderCreate: no ServerId in response")
        return Folder(id=server_id, parent_id=parent_id, type=type, name=display_name)

    def update_folder(self, folder_id: str, display_name: str, parent_id: str = "0") -> None:
        self._ensure_provisioned()
        sync_key = self._folder_sync_key()
        w = WBXMLWriter()
        w.tag(
            "FolderHierarchy",
            "FolderUpdate",
            children=[
                wtag("FolderHierarchy", "SyncKey", text=sync_key),
                wtag("FolderHierarchy", "ServerId", text=folder_id),
                wtag("FolderHierarchy", "ParentId", text=parent_id),
                wtag("FolderHierarchy", "DisplayName", text=display_name),
            ],
        )
        resp = self._post("FolderUpdate", w.render())
        status = text_of(find(WBXMLReader(resp).parse(), "FolderHierarchy.Status"))
        _check_status("FolderUpdate", status)

    def delete_folder(self, folder_id: str) -> None:
        self._ensure_provisioned()
        sync_key = self._folder_sync_key()
        w = WBXMLWriter()
        w.tag(
            "FolderHierarchy",
            "FolderDelete",
            children=[
                wtag("FolderHierarchy", "SyncKey", text=sync_key),
                wtag("FolderHierarchy", "ServerId", text=folder_id),
            ],
        )
        resp = self._post("FolderDelete", w.render())
        status = text_of(find(WBXMLReader(resp).parse(), "FolderHierarchy.Status"))
        _check_status("FolderDelete", status)

    # -- Sync ------------------------------------------------------------------

    def sync_folder(
        self,
        folder_id: str,
        sync_key: str = "0",
        *,
        window_size: int = 25,
        filter_type: str | None = None,
    ) -> SyncResult:
        """``Sync`` one collection. Pass ``sync_key="0"`` (the default) to bootstrap.

        A bootstrap request only returns a fresh ``SyncKey``, no items --
        call again with that key to fetch the actual ``Add``/``Change``/``Delete``
        entries, exactly as the protocol requires.
        """
        self._ensure_provisioned()
        options = [wtag("AirSync", "FilterType", text=filter_type)] if filter_type else []
        collection_children = [
            wtag("AirSync", "SyncKey", text=sync_key),
            wtag("AirSync", "CollectionId", text=folder_id),
            wtag("AirSync", "WindowSize", text=str(window_size)),
        ]
        if options:
            collection_children.append(wtag("AirSync", "Options", children=options))
        w = WBXMLWriter()
        w.tag(
            "AirSync",
            "Sync",
            children=[
                wtag(
                    "AirSync",
                    "Collections",
                    children=[wtag("AirSync", "Collection", children=collection_children)],
                ),
            ],
        )
        resp = self._post("Sync", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "AirSync.Status"))
        _check_status("Sync", status)
        new_sync_key = text_of(find(nodes, "AirSync.SyncKey")) or sync_key

        added = [self._sync_item(c) for _, _, c in find_all(nodes, "AirSync.Add")]
        changed = [self._sync_item(c) for _, _, c in find_all(nodes, "AirSync.Change")]
        deleted = [
            sid
            for _, _, c in find_all(nodes, "AirSync.Delete")
            if (sid := text_of(find(c, "AirSync.ServerId"))) is not None
        ]
        more_available = find(nodes, "AirSync.MoreAvailable") is not None
        return SyncResult(
            sync_key=new_sync_key, added=added, changed=changed, deleted=deleted, more_available=more_available
        )

    @staticmethod
    def _sync_item(children: list[Node]) -> SyncItem:
        server_id = text_of(find(children, "AirSync.ServerId")) or ""
        appdata = find(children, "AirSync.ApplicationData")
        return SyncItem(server_id=server_id, fields=leaves(appdata[2]) if appdata else {})

    def apply_email_changes(
        self,
        folder_id: str,
        sync_key: str,
        changes: Iterable[EmailChange],
        *,
        deletes_as_moves: bool = True,
    ) -> EmailChangesResult:
        """Apply read, follow-up flag, and delete mutations through ``Sync``.

        ``sync_key`` must be the latest non-zero key returned by
        :meth:`sync_folder` or this method. Successful changes often have no
        per-item response in EAS, in which case their status is reported as
        ``"1"``. Set ``deletes_as_moves=False`` for permanent deletion rather
        than moving deleted items to the Deleted Items folder.
        """
        if not folder_id:
            raise ValueError("folder_id must not be empty")
        if not sync_key or sync_key == "0":
            raise ValueError("sync_key must be a non-zero synchronized key")
        requested = list(changes)
        if not requested:
            raise ValueError("at least one email change is required")

        commands = []
        statuses: dict[str, str] = {}
        flag_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        for change in requested:
            if not change.server_id:
                raise ValueError("email change server_id must not be empty")
            if change.server_id in statuses:
                raise ValueError(f"duplicate email change for server_id {change.server_id!r}")
            if change.delete and (change.read is not None or change.flagged is not None):
                raise ValueError("a delete cannot be combined with read or flag changes")
            if not change.delete and change.read is None and change.flagged is None:
                raise ValueError("email change has no mutation")
            statuses[change.server_id] = "1"

            if change.delete:
                commands.append(
                    wtag(
                        "AirSync",
                        "Delete",
                        children=[wtag("AirSync", "ServerId", text=change.server_id)],
                    )
                )
                continue

            application_data = []
            if change.read is not None:
                application_data.append(wtag("Email", "Read", text="1" if change.read else "0"))
            if change.flagged is not None:
                flag_children = [wtag("Email", "Status", text="2" if change.flagged else "0")]
                if change.flagged:
                    # MS-ASEMAIL requires active flags to include their type and
                    # either start/due dates or completion dates. Sending only
                    # Status=2, as some clients do, can fail with Sync Status=6.
                    flag_children.extend(
                        [
                            wtag("Email", "FlagType", text="Flag for follow up"),
                            wtag("Tasks", "StartDate", text=flag_time),
                            wtag("Tasks", "UtcStartDate", text=flag_time),
                            wtag("Tasks", "DueDate", text=flag_time),
                            wtag("Tasks", "UtcDueDate", text=flag_time),
                        ]
                    )
                application_data.append(wtag("Email", "Flag", children=flag_children))
            commands.append(
                wtag(
                    "AirSync",
                    "Change",
                    children=[
                        wtag("AirSync", "ServerId", text=change.server_id),
                        wtag("AirSync", "ApplicationData", children=application_data),
                    ],
                )
            )

        new_sync_key, statuses = self._sync_mutate(folder_id, sync_key, commands, statuses, deletes_as_moves)
        return EmailChangesResult(sync_key=new_sync_key, statuses=statuses)

    def apply_contact_changes(
        self,
        folder_id: str,
        sync_key: str,
        changes: Iterable[ContactChange],
        *,
        deletes_as_moves: bool = True,
    ) -> ContactChangesResult:
        """Apply contact field updates and deletes through ``Sync``.

        ``sync_key`` must be the latest non-zero key returned by
        :meth:`sync_folder` or this method. Successful changes often have no
        per-item response in EAS, in which case their status is reported as
        ``"1"``. Set ``deletes_as_moves=False`` for permanent deletion rather
        than moving deleted items to the Deleted Items folder.

        Live EAS testing against a real Exchange server showed a contact
        update does not merge: properties left off ``ContactChange.contact``
        were cleared, not preserved (unlike ``apply_email_changes``' Read/Flag
        mutations, which are genuinely partial). Send the full desired
        :class:`~pyactivesync.models.Contact` field set on every update.
        """
        if not folder_id:
            raise ValueError("folder_id must not be empty")
        if not sync_key or sync_key == "0":
            raise ValueError("sync_key must be a non-zero synchronized key")
        requested = list(changes)
        if not requested:
            raise ValueError("at least one contact change is required")

        commands = []
        statuses: dict[str, str] = {}
        for change in requested:
            if not change.server_id:
                raise ValueError("contact change server_id must not be empty")
            if change.server_id in statuses:
                raise ValueError(f"duplicate contact change for server_id {change.server_id!r}")
            contact = change.contact
            if change.delete and contact is not None:
                raise ValueError("a delete cannot be combined with a contact update")
            if not change.delete and contact is None:
                raise ValueError("contact change has no mutation")
            statuses[change.server_id] = "1"

            if change.delete:
                commands.append(
                    wtag(
                        "AirSync",
                        "Delete",
                        children=[wtag("AirSync", "ServerId", text=change.server_id)],
                    )
                )
                continue

            assert contact is not None
            application_data = _contact_application_data(contact)
            if not application_data:
                raise ValueError(f"contact change for server_id {change.server_id!r} has no fields set")
            commands.append(
                wtag(
                    "AirSync",
                    "Change",
                    children=[
                        wtag("AirSync", "ServerId", text=change.server_id),
                        wtag("AirSync", "ApplicationData", children=application_data),
                    ],
                )
            )

        new_sync_key, statuses = self._sync_mutate(folder_id, sync_key, commands, statuses, deletes_as_moves)
        return ContactChangesResult(sync_key=new_sync_key, statuses=statuses)

    def _sync_mutate(
        self,
        folder_id: str,
        sync_key: str,
        commands: list[NodeBuilder],
        statuses: dict[str, str],
        deletes_as_moves: bool,
    ) -> tuple[str, dict[str, str]]:
        """Shared ``Sync`` Change/Delete plumbing: send the given commands and
        overwrite ``statuses`` with any explicit per-item status the server
        returns. Returns ``(new_sync_key, statuses)``.
        """
        self._ensure_provisioned()
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
                                wtag("AirSync", "SyncKey", text=sync_key),
                                wtag("AirSync", "CollectionId", text=folder_id),
                                wtag("AirSync", "DeletesAsMoves", text="1" if deletes_as_moves else "0"),
                                wtag("AirSync", "GetChanges", text="0"),
                                wtag("AirSync", "Commands", children=commands),
                            ],
                        )
                    ],
                )
            ],
        )
        # A mutation is not retried blindly: the server may have committed it
        # before returning a transient HTTP error.
        resp = self._post("Sync", w.render())
        nodes = WBXMLReader(resp).parse()
        root = find(nodes, "AirSync.Sync")
        if root is None:
            raise ProtocolError("Sync changes: no Sync response")
        _check_status("Sync", text_of(_direct_find(root[2], "AirSync.Status")))
        collections = _direct_find(root[2], "AirSync.Collections")
        collection = _direct_find(collections[2], "AirSync.Collection") if collections else None
        if collection is None:
            raise ProtocolError("Sync changes: no Collection in response")
        _check_status("Sync", text_of(_direct_find(collection[2], "AirSync.Status")))
        new_sync_key = text_of(_direct_find(collection[2], "AirSync.SyncKey"))
        if not new_sync_key:
            raise ProtocolError("Sync changes: no SyncKey in response")
        responses = _direct_find(collection[2], "AirSync.Responses")
        if responses is not None:
            for name, _, children in responses[2]:
                if name not in {"AirSync.Change", "AirSync.Delete"}:
                    continue
                server_id = text_of(_direct_find(children, "AirSync.ServerId"))
                status = text_of(_direct_find(children, "AirSync.Status"))
                if server_id is not None and status is not None:
                    statuses[server_id] = status
        return new_sync_key, statuses

    def create_email_draft(
        self,
        folder_id: str,
        sync_key: str,
        message: Message,
        *,
        read: bool = False,
        flagged: bool = False,
        client_id: str | None = None,
    ) -> EmailAddResult:
        """Create one draft email through EAS 16.1 ``Sync Add``.

        EAS 16.1 supports client-originated ``Sync`` Add for draft email
        only -- there is no IMAP-style arbitrary-folder ``APPEND``.
        ``folder_id`` should identify the mailbox's Drafts folder and
        ``sync_key`` must be its latest non-zero key.  Exchange rejects
        non-draft additions with item status ``"6"``.  The result always
        includes the advanced collection ``SyncKey`` and the ``ClientId``;
        successful additions also include the assigned ``ServerId``.  The
        returned key must be used for the next operation on this collection.

        The complete stdlib message is stored as a MIME body, preserving its
        headers, body alternatives, and attachments.  ``client_id`` is
        generated when omitted and can be supplied by callers that need to
        correlate an operation with durable local state.  Live EAS 16.1
        testing confirmed Exchange accepts this MIME draft path, including
        attachment round-trips and read/follow-up flag state.
        """
        if not folder_id:
            raise ValueError("folder_id must not be empty")
        if not sync_key or sync_key == "0":
            raise ValueError("sync_key must be a non-zero synchronized key")
        if not isinstance(message, Message):
            raise TypeError("message must be an email.message.Message")
        item_client_id = client_id if client_id is not None else uuid.uuid4().hex
        if not item_client_id:
            raise ValueError("client_id must not be empty")

        application_data = [
            wtag(
                "AirSyncBase",
                "Body",
                children=[
                    wtag("AirSyncBase", "Type", text=str(int(BodyType.MIME))),
                    wtag("AirSyncBase", "Data", text=to_7bit_crlf_text(message)),
                ],
            ),
            wtag("Email", "Read", text="1" if read else "0"),
        ]
        if flagged:
            flag_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
            application_data.append(
                wtag(
                    "Email",
                    "Flag",
                    children=[
                        wtag("Email", "Status", text="2"),
                        wtag("Email", "FlagType", text="Flag for follow up"),
                        wtag("Tasks", "StartDate", text=flag_time),
                        wtag("Tasks", "UtcStartDate", text=flag_time),
                        wtag("Tasks", "DueDate", text=flag_time),
                        wtag("Tasks", "UtcDueDate", text=flag_time),
                    ],
                )
            )

        new_sync_key, status, server_id = self._sync_add(folder_id, sync_key, application_data, item_client_id)
        return EmailAddResult(
            sync_key=new_sync_key,
            client_id=item_client_id,
            status=status,
            server_id=server_id,
        )

    def create_contact(
        self,
        folder_id: str,
        sync_key: str,
        contact: Contact,
        *,
        client_id: str | None = None,
    ) -> ContactAddResult:
        """Create one contact through EAS ``Sync Add``.

        ``folder_id`` should identify the mailbox's Contacts folder and
        ``sync_key`` must be its latest non-zero key. Only the fields set on
        ``contact`` (see :class:`~pyactivesync.models.Contact`) are sent.
        The result always includes the advanced collection ``SyncKey`` and
        the ``ClientId``; successful additions also include the assigned
        ``ServerId``. The returned key must be used for the next operation
        on this collection.
        """
        if not folder_id:
            raise ValueError("folder_id must not be empty")
        if not sync_key or sync_key == "0":
            raise ValueError("sync_key must be a non-zero synchronized key")
        if not isinstance(contact, Contact):
            raise TypeError("contact must be a Contact")
        application_data = _contact_application_data(contact)
        if not application_data:
            raise ValueError("contact has no fields set")
        item_client_id = client_id if client_id is not None else uuid.uuid4().hex
        if not item_client_id:
            raise ValueError("client_id must not be empty")

        new_sync_key, status, server_id = self._sync_add(folder_id, sync_key, application_data, item_client_id)
        return ContactAddResult(
            sync_key=new_sync_key,
            client_id=item_client_id,
            status=status,
            server_id=server_id,
        )

    def _sync_add(
        self, folder_id: str, sync_key: str, application_data: list[NodeBuilder], client_id: str
    ) -> tuple[str, str, str | None]:
        """Shared ``Sync Add`` plumbing: send one Add command, parse the
        response's ``SyncKey``, and locate the per-item ``Status``/``ServerId``
        for ``client_id``. Returns ``(new_sync_key, status, server_id)``.
        """
        self._ensure_provisioned()
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
                                wtag("AirSync", "SyncKey", text=sync_key),
                                wtag("AirSync", "CollectionId", text=folder_id),
                                wtag("AirSync", "GetChanges", text="0"),
                                wtag(
                                    "AirSync",
                                    "Commands",
                                    children=[
                                        wtag(
                                            "AirSync",
                                            "Add",
                                            children=[
                                                wtag("AirSync", "ClientId", text=client_id),
                                                wtag(
                                                    "AirSync",
                                                    "ApplicationData",
                                                    children=application_data,
                                                ),
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
        # Sync Add is non-idempotent: a transport failure can occur after the
        # server created the item, so the request must not be retried blindly.
        resp = self._post("Sync", w.render())
        nodes = WBXMLReader(resp).parse()
        root = find(nodes, "AirSync.Sync")
        if root is None:
            raise ProtocolError("Sync Add: no Sync response")
        _check_status("Sync", text_of(_direct_find(root[2], "AirSync.Status")))
        collections = _direct_find(root[2], "AirSync.Collections")
        collection = _direct_find(collections[2], "AirSync.Collection") if collections else None
        if collection is None:
            raise ProtocolError("Sync Add: no Collection in response")
        _check_status("Sync", text_of(_direct_find(collection[2], "AirSync.Status")))
        new_sync_key = text_of(_direct_find(collection[2], "AirSync.SyncKey"))
        if not new_sync_key:
            raise ProtocolError("Sync Add: no SyncKey in response")

        responses = _direct_find(collection[2], "AirSync.Responses")
        additions = [node for node in (responses[2] if responses else []) if node[0] == "AirSync.Add"]
        addition = next(
            (node for node in additions if text_of(_direct_find(node[2], "AirSync.ClientId")) == client_id),
            None,
        )
        if addition is None:
            raise ProtocolError(f"Sync Add: no response for ClientId {client_id!r}")
        status = text_of(_direct_find(addition[2], "AirSync.Status"))
        if status is None:
            raise ProtocolError("Sync Add: item response has no Status")
        server_id = text_of(_direct_find(addition[2], "AirSync.ServerId"))
        if status == "1" and not server_id:
            raise ProtocolError("Sync Add: successful item response has no ServerId")
        return new_sync_key, status, server_id

    def get_item_estimate(self, folder_id: str, sync_key: str) -> int:
        """``GetItemEstimate`` needs a real (non-zero) ``SyncKey`` -- bootstrap one via ``sync_folder`` first."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "ItemEstimate",
            "GetItemEstimate",
            children=[
                wtag(
                    "ItemEstimate",
                    "Collections",
                    children=[
                        wtag(
                            "ItemEstimate",
                            "Collection",
                            children=[
                                wtag("AirSync", "SyncKey", text=sync_key),
                                wtag("ItemEstimate", "CollectionId", text=folder_id),
                            ],
                        ),
                    ],
                ),
            ],
        )
        resp = self._post("GetItemEstimate", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "ItemEstimate.Status"))
        _check_status("GetItemEstimate", status)
        estimate = text_of(find(nodes, "ItemEstimate.Estimate"))
        if estimate is None:
            raise ProtocolError("GetItemEstimate: no Estimate in response")
        return int(estimate)

    # -- Items -------------------------------------------------------------------

    def fetch_item(self, folder_id: str, item_id: str, *, body_type: BodyType = BodyType.HTML) -> FetchedItem:
        """``ItemOperations`` Fetch preserving bodies and attachment metadata.

        Returns a typed ``FetchedItem``, not a flattened property map. Its
        ordered ``bodies`` and ``attachments`` lists preserve repeated EAS
        containers; ``body`` is a convenience alias for the first body. Other
        scalar properties remain available through ``FetchedItem.fields``.

        The operation does not mark the item read. MIME body data is returned
        as bytes; plain text, HTML, and RTF data retain the WBXML value type.
        Each attachment retains its own file reference, display name, size,
        method, content identifiers, and inline state.
        """
        self._ensure_provisioned()
        option_children = [
            wtag(
                "AirSyncBase",
                "BodyPreference",
                children=[wtag("AirSyncBase", "Type", text=str(int(body_type)))],
            )
        ]
        if body_type == BodyType.MIME:
            option_children.append(wtag("AirSync", "MIMESupport", text="2"))
        w = WBXMLWriter()
        w.tag(
            "ItemOperations",
            "ItemOperations",
            children=[
                wtag(
                    "ItemOperations",
                    "Fetch",
                    children=[
                        wtag("ItemOperations", "Store", text="Mailbox"),
                        wtag("AirSync", "CollectionId", text=folder_id),
                        wtag("AirSync", "ServerId", text=item_id),
                        wtag(
                            "ItemOperations",
                            "Options",
                            children=option_children,
                        ),
                    ],
                ),
            ],
        )
        resp = self._post("ItemOperations", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        root = find(nodes, "ItemOperations.ItemOperations")
        if root is None:
            raise ProtocolError("ItemOperations Fetch: no ItemOperations response")
        _check_status("ItemOperations", text_of(_direct_find(root[2], "ItemOperations.Status")))
        response = _direct_find(root[2], "ItemOperations.Response")
        fetch = _direct_find(response[2], "ItemOperations.Fetch") if response else None
        if fetch is None:
            raise ProtocolError("ItemOperations Fetch: no Fetch response")
        _check_status("ItemOperations Fetch", text_of(_direct_find(fetch[2], "ItemOperations.Status")))
        props = _direct_find(fetch[2], "ItemOperations.Properties")
        return self._fetched_item(props[2] if props else [])

    @classmethod
    def _fetched_item(cls, nodes: list[Node]) -> FetchedItem:
        bodies = [cls._item_body(children) for _, _, children in find_all(nodes, "AirSyncBase.Body")]
        attachments = [
            cls._attachment_info(children) for _, _, children in find_all(nodes, "AirSyncBase.Attachment")
        ]
        structured = {
            "AirSyncBase.Attachments",
            "AirSyncBase.Body",
            "AirSyncBase.NativeBodyType",
            "AirSyncBase.ContentType",
        }
        native_text = text_of(_direct_find(nodes, "AirSyncBase.NativeBodyType"))
        return FetchedItem(
            fields=leaves([node for node in nodes if node[0] not in structured]),
            bodies=bodies,
            attachments=attachments,
            native_body_type=cls._body_type(native_text, "NativeBodyType") if native_text is not None else None,
            content_type=text_of(_direct_find(nodes, "AirSyncBase.ContentType")),
        )

    @classmethod
    def _item_body(cls, nodes: list[Node]) -> ItemBody:
        type_text = text_of(_direct_find(nodes, "AirSyncBase.Type"))
        if type_text is None:
            raise ProtocolError("ItemOperations Fetch: Body has no Type")
        body_type = cls._body_type(type_text, "Body.Type")
        data_node = _direct_find(nodes, "AirSyncBase.Data")
        data: str | bytes | None = opaque_of(data_node)
        if data is None:
            data = text_of(data_node)
        if body_type == BodyType.MIME and isinstance(data, str):
            data = data.encode("utf-8")
        return ItemBody(
            type=body_type,
            data=data,
            estimated_data_size=cls._optional_int(nodes, "AirSyncBase.EstimatedDataSize"),
            truncated=cls._optional_bool(nodes, "AirSyncBase.Truncated"),
            part=text_of(_direct_find(nodes, "ItemOperations.Part")),
            preview=text_of(_direct_find(nodes, "AirSyncBase.Preview")),
        )

    @classmethod
    def _attachment_info(cls, nodes: list[Node]) -> AttachmentInfo:
        file_reference = text_of(_direct_find(nodes, "AirSyncBase.FileReference"))
        if not file_reference:
            raise ProtocolError("ItemOperations Fetch: Attachment has no FileReference")
        return AttachmentInfo(
            file_reference=file_reference,
            display_name=text_of(_direct_find(nodes, "AirSyncBase.DisplayName")),
            method=cls._optional_int(nodes, "AirSyncBase.Method"),
            content_type=text_of(_direct_find(nodes, "AirSyncBase.ContentType")),
            estimated_data_size=cls._optional_int(nodes, "AirSyncBase.EstimatedDataSize"),
            content_id=text_of(_direct_find(nodes, "AirSyncBase.ContentId")),
            content_location=text_of(_direct_find(nodes, "AirSyncBase.ContentLocation")),
            is_inline=_direct_find(nodes, "AirSyncBase.IsInline") is not None,
        )

    @staticmethod
    def _body_type(value: str, field: str) -> BodyType:
        try:
            return BodyType(int(value))
        except (TypeError, ValueError) as exc:
            raise ProtocolError(f"ItemOperations Fetch: invalid {field} value {value!r}") from exc

    @staticmethod
    def _optional_int(nodes: list[Node], path: str) -> int | None:
        value = text_of(_direct_find(nodes, path))
        if value is None:
            return None
        try:
            return int(value)
        except ValueError as exc:
            raise ProtocolError(f"ItemOperations Fetch: invalid {path} value {value!r}") from exc

    @staticmethod
    def _optional_bool(nodes: list[Node], path: str) -> bool | None:
        node = _direct_find(nodes, path)
        if node is None:
            return None
        value = text_of(node)
        if value is None:
            return True
        if value in {"0", "1"}:
            return value == "1"
        raise ProtocolError(f"ItemOperations Fetch: invalid {path} value {value!r}")

    def fetch_attachment(self, file_reference: str) -> bytes:
        """``ItemOperations`` Fetch by ``FileReference``. Returns decoded attachment bytes."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "ItemOperations",
            "ItemOperations",
            children=[
                wtag(
                    "ItemOperations",
                    "Fetch",
                    children=[
                        wtag("ItemOperations", "Store", text="Mailbox"),
                        wtag("AirSyncBase", "FileReference", text=file_reference),
                    ],
                ),
            ],
        )
        resp = self._post("ItemOperations", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "ItemOperations.Status"))
        _check_status("ItemOperations", status)
        b64 = text_of(find(nodes, "ItemOperations.Data"))
        return base64.b64decode(b64) if b64 else b""

    def move_item(self, item_id: str, src_folder_id: str, dst_folder_id: str) -> str:
        """``MoveItems``. Returns the new (destination) ``ServerId``."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Move",
            "MoveItems",
            children=[
                wtag(
                    "Move",
                    "Move",
                    children=[
                        wtag("Move", "SrcMsgId", text=item_id),
                        wtag("Move", "SrcFldId", text=src_folder_id),
                        wtag("Move", "DstFldId", text=dst_folder_id),
                    ],
                ),
            ],
        )
        resp = self._post("MoveItems", w.render())
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Move.Status"))
        if status is not None and status != "3":
            raise StatusError("MoveItems", status, _MOVEITEMS_STATUS_MEANINGS.get(status))
        new_id = text_of(find(nodes, "Move.DstMsgId"))
        if not new_id:
            raise ProtocolError("MoveItems: no DstMsgId in response")
        return new_id

    # -- Mail --------------------------------------------------------------------

    def send_mail(
        self,
        message: Message,
        *,
        save_in_sent_items: bool = True,
        client_id: str | None = None,
    ) -> None:
        """``SendMail``: WBXML ``ComposeMail`` wrapper, MIME embedded as opaque data.

        Protocol v16.1 requires the
        ``ComposeMail`` WBXML wrapper -- unlike v12.0/12.1, a raw
        ``message/rfc822`` POST body is rejected.  ``client_id`` defaults to a
        new UUID hex string and can be supplied by callers that persist their
        own submission identifier.  Reusing an ID does not make retrying safe:
        duplicate detection is server-dependent and SendMail remains
        non-idempotent.
        """
        item_client_id = client_id if client_id is not None else uuid.uuid4().hex
        _validate_compose_client_id(item_client_id)
        self._ensure_provisioned()
        mime_bytes = to_crlf_bytes(message)
        children = [wtag("ComposeMail", "ClientId", text=item_client_id)]
        if save_in_sent_items:
            children.append(wtag("ComposeMail", "SaveInSentItems"))
        children.append(wtag("ComposeMail", "MIME", opaque=mime_bytes))
        w = WBXMLWriter()
        w.tag("ComposeMail", "SendMail", children=children)
        resp = self._post("SendMail", w.render())
        if resp:
            status = text_of(find(WBXMLReader(resp).parse(), "ComposeMail.Status"))
            _check_status("SendMail", status, _SENDMAIL_STATUS_MEANINGS)

    # -- Device / connectivity ----------------------------------------------------

    @overload
    def ping(
        self,
        folder_ids: str | Iterable[str],
        *,
        folder_class: str = "Email",
        heartbeat: int = 60,
        timeout: float | None = None,
    ) -> PingResult: ...

    @overload
    def ping(
        self,
        *,
        folder_id: str,
        folder_class: str = "Email",
        heartbeat: int = 60,
        timeout: float | None = None,
    ) -> PingResult: ...

    def ping(
        self,
        folder_ids: str | Iterable[str] | None = None,
        *,
        folder_id: str | None = None,
        folder_class: str = "Email",
        heartbeat: int = 60,
        timeout: float | None = None,
    ) -> PingResult:
        """``Ping``: long-poll for changes on one or more folders.

        ``timeout`` bounds the client-side wait; it is independent of
        ``heartbeat`` (the server-side long-poll duration requested).

        A string monitors one folder; an iterable of folder ids monitors the
        whole set in one request. ``folder_id`` is retained as a keyword-only
        compatibility alias for the former single-folder API.
        """
        if folder_ids is not None and folder_id is not None:
            raise TypeError("pass folder_ids or folder_id, not both")
        requested = folder_ids if folder_ids is not None else folder_id
        if requested is None:
            raise TypeError("missing required folder_ids")
        requested_folder_ids = [requested] if isinstance(requested, str) else list(requested)
        if not requested_folder_ids:
            raise ValueError("at least one folder id is required")
        if any(not isinstance(item, str) or not item for item in requested_folder_ids):
            raise ValueError("folder ids must be non-empty strings")

        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Ping",
            "Ping",
            children=[
                wtag("Ping", "HeartbeatInterval", text=str(heartbeat)),
                wtag(
                    "Ping",
                    "Folders",
                    children=[
                        wtag(
                            "Ping",
                            "Folder",
                            children=[
                                wtag("Ping", "Id", text=folder_id),
                                wtag("Ping", "Class", text=folder_class),
                            ],
                        )
                        for folder_id in requested_folder_ids
                    ],
                ),
            ],
        )
        resp = self._post("Ping", w.render(), timeout=timeout, idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Ping.Status")) or ""
        changed = [
            sid
            for folder in find_all(nodes, "Ping.Folder")
            if (sid := text_of(folder)) is not None
        ]
        return PingResult(status=status, changed_folder_ids=changed)

    # -- Directory / search --------------------------------------------------------

    def resolve_recipients(self, address: str) -> list[Recipient]:
        """Resolve one address against contacts/GAL."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag("ResolveRecipients", "ResolveRecipients", children=[wtag("ResolveRecipients", "To", text=address)])
        resp = self._post("ResolveRecipients", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "ResolveRecipients.Status"))
        _check_status("ResolveRecipients", status)
        recipients = []
        for _, _, children in find_all(nodes, "ResolveRecipients.Recipient"):
            data = leaves(children)
            recipients.append(
                Recipient(
                    type=data.get("ResolveRecipients.Type"),
                    display_name=data.get("ResolveRecipients.DisplayName"),
                    email_address=data.get("ResolveRecipients.EmailAddress"),
                )
            )
        return recipients

    def search_gal(self, query: str, *, max_results: int = 10) -> list[GalEntry]:
        """GAL (directory) search."""
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Search",
            "Search",
            children=[
                wtag(
                    "Search",
                    "Store",
                    children=[
                        wtag("Search", "Name", text="GAL"),
                        wtag("Search", "Query", text=query),
                        wtag("Search", "Options", children=[wtag("Search", "Range", text=f"0-{max_results - 1}")]),
                    ],
                ),
            ],
        )
        resp = self._post("Search", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Search.Status"))
        _check_status("Search", status)
        entries = []
        for _, _, children in find_all(nodes, "Search.Result"):
            data = leaves(children)
            entries.append(
                GalEntry(
                    display_name=data.get("GAL.DisplayName"),
                    email_address=data.get("GAL.EmailAddress"),
                    phone=data.get("GAL.Phone"),
                    office=data.get("GAL.Office"),
                    title=data.get("GAL.Title"),
                    company=data.get("GAL.Company"),
                    alias=data.get("GAL.Alias"),
                    first_name=data.get("GAL.FirstName"),
                    last_name=data.get("GAL.LastName"),
                    home_phone=data.get("GAL.HomePhone"),
                    mobile_phone=data.get("GAL.MobilePhone"),
                )
            )
        return entries

    def search_mailbox(
        self,
        folder_id: str,
        *,
        date_received_after: str | None = None,
        free_text: str | None = None,
        item_class: str = "Email",
        max_results: int = 10,
    ) -> list[dict[str, str]]:
        """Mailbox search: items of ``item_class`` in ``folder_id``, either
        received after ``date_received_after`` (an ``AirSyncBase``-style UTC
        timestamp, e.g. ``"2020-01-01T00:00:00.000Z"``) or matching
        ``free_text``. Exactly one of the two must be given.

        A ``FreeText`` condition on the ``Search`` command itself is known to
        fail against real servers with ``Store.Status=110`` -- a server-side
        bug in EAS's ``Search`` handling, not a WBXML encoding issue
        (confirmed by cross-checking the same mailbox's content index through
        an unrelated protocol, which returns correct results for the same
        query; re-confirmed live as of 2026-08-23 -- still broken
        server-side). ``free_text=`` here is served through the EAS 16.1
        ``Find`` command instead (see ``find_mailbox``), which implements
        full-text search correctly, and the result is adapted back to this
        method's ``list[dict[str, str]]`` shape. Callers who need pagination
        or the raw ``FindResult`` should call ``find_mailbox`` directly.
        """
        if (date_received_after is None) == (free_text is None):
            raise ValueError("pass exactly one of date_received_after or free_text")
        if free_text is not None:
            result = self.find_mailbox(free_text, folder_id=folder_id, item_class=item_class, max_results=max_results)
            return [
                {
                    **({"AirSync.ServerId": item.server_id} if item.server_id is not None else {}),
                    **({"AirSync.CollectionId": item.collection_id} if item.collection_id is not None else {}),
                    **item.fields,
                }
                for item in result.items
            ]
        assert date_received_after is not None
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Search",
            "Search",
            children=[
                wtag(
                    "Search",
                    "Store",
                    children=[
                        wtag("Search", "Name", text="Mailbox"),
                        wtag(
                            "Search",
                            "Query",
                            children=[
                                wtag(
                                    "Search",
                                    "And",
                                    children=[
                                        wtag("AirSync", "Class", text=item_class),
                                        wtag("AirSync", "CollectionId", text=folder_id),
                                        wtag(
                                            "Search",
                                            "GreaterThan",
                                            children=[
                                                wtag("Email", "DateReceived"),
                                                wtag("Search", "Value", text=date_received_after),
                                            ],
                                        ),
                                    ],
                                ),
                            ],
                        ),
                        wtag("Search", "Options", children=[wtag("Search", "Range", text=f"0-{max_results - 1}")]),
                    ],
                ),
            ],
        )
        resp = self._post("Search", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Search.Status"))
        _check_status("Search", status)
        return [leaves(children) for _, _, children in find_all(nodes, "Search.Result")]

    def find_mailbox(
        self,
        query: str,
        *,
        folder_id: str | None = None,
        item_class: str = "Email",
        range_start: int = 0,
        max_results: int = 10,
        deep_traversal: bool = False,
        search_id: str | None = None,
    ) -> FindResult:
        """Free-text mailbox search using the EAS 16.1 ``Find`` command.

        Pass the returned ``search_id`` back with a later ``range_start`` to
        request another page of the same search. If ``folder_id`` is omitted,
        Exchange searches all folders; ``deep_traversal`` requests recursive
        traversal where the server supports it.
        """
        if not query.strip():
            raise ValueError("query must not be empty")
        query_children = [
            wtag("Find", "FreeText", text=query),
            wtag("AirSync", "Class", text=item_class),
        ]
        if folder_id is not None:
            query_children.append(wtag("AirSync", "CollectionId", text=folder_id))
        return self._find(
            "MailBoxSearchCriterion",
            wtag("Find", "Query", children=query_children),
            range_start=range_start,
            max_results=max_results,
            deep_traversal=deep_traversal,
            search_id=search_id,
        )

    def find_gal(
        self,
        query: str,
        *,
        range_start: int = 0,
        max_results: int = 10,
        search_id: str | None = None,
    ) -> FindResult:
        """Search the Global Address List using the EAS 16.1 ``Find`` command."""
        if not 4 <= len(query) <= 256:
            raise ValueError("GAL Find query must contain 4 to 256 characters")
        return self._find(
            "GALSearchCriterion",
            wtag("Find", "Query", text=query),
            range_start=range_start,
            max_results=max_results,
            search_id=search_id,
        )

    def _find(
        self,
        criterion_name: str,
        query: NodeBuilder,
        *,
        range_start: int,
        max_results: int,
        deep_traversal: bool = False,
        search_id: str | None,
    ) -> FindResult:
        if range_start < 0:
            raise ValueError("range_start must be non-negative")
        if not 1 <= max_results <= 1000 or range_start + max_results > 1000:
            raise ValueError("requested range must be within 0-999")
        if search_id is None:
            search_id = str(uuid.uuid4())
        else:
            try:
                search_id = str(uuid.UUID(search_id))
            except ValueError as exc:
                raise ValueError("search_id must be a UUID") from exc

        options = [wtag("Find", "Range", text=f"{range_start}-{range_start + max_results - 1}")]
        if deep_traversal:
            options.append(wtag("Find", "DeepTraversal"))
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Find",
            "Find",
            children=[
                wtag("Find", "SearchId", text=search_id),
                wtag(
                    "Find",
                    "ExecuteSearch",
                    children=[
                        wtag(
                            "Find",
                            criterion_name,
                            children=[query, wtag("Find", "Options", children=options)],
                        )
                    ],
                ),
            ],
        )
        resp = self._post("Find", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        status = text_of(find(nodes, "Find.Status")) or "1"
        _check_status("Find", status)
        response = find(nodes, "Find.Response")
        if response is None:
            return FindResult(search_id=search_id, status=status)
        response_status = text_of(find(response[2], "Find.Status")) or "1"
        _check_status("Find", response_status)
        items = []
        for _, _, children in find_all(response[2], "Find.Result"):
            properties = find(children, "Find.Properties")
            items.append(
                FindItem(
                    server_id=text_of(find(children, "AirSync.ServerId")),
                    collection_id=text_of(find(children, "AirSync.CollectionId")),
                    fields=leaves(properties[2]) if properties is not None else {},
                )
            )
        return FindResult(
            search_id=search_id,
            status=response_status,
            range=text_of(find(response[2], "Find.Range")),
            # Find:Total describes available entries, not necessarily entries
            # returned, and real Exchange servers can even send Total=0 with a
            # non-empty page. Report the actual decoded Result count instead.
            total=len(items),
            items=items,
        )

    # -- Settings ------------------------------------------------------------------

    def get_oof(self) -> OofSettings:
        """``Settings`` Oof Get: current Out-of-Office autoreply configuration.

        Request shape verified against a real Exchange server; the response
        parsing below follows the MS-ASCMD schema but hasn't itself been
        cross-checked against a live response.
        """
        self._ensure_provisioned()
        w = WBXMLWriter()
        w.tag(
            "Settings",
            "Settings",
            children=[
                wtag(
                    "Settings",
                    "Oof",
                    children=[wtag("Settings", "Get", children=[wtag("Settings", "BodyType", text="Text")])],
                ),
            ],
        )
        resp = self._post("Settings", w.render(), idempotent=True)
        nodes = WBXMLReader(resp).parse()
        _check_status("Settings", text_of(find(nodes, "Settings.Status")))
        oof = find(nodes, "Settings.Oof")
        if oof is None:
            raise ProtocolError("Settings: no Oof in Get response")
        _check_status("Settings.Oof", text_of(find(oof[2], "Settings.Status")))
        get = find(oof[2], "Settings.Get")
        if get is None:
            raise ProtocolError("Settings: no Oof.Get in response")
        state = text_of(find(get[2], "Settings.OofState"))
        messages = [self._oof_message(children) for _, _, children in find_all(get[2], "Settings.OofMessage")]
        return OofSettings(
            state=OofState(int(state)) if state is not None else OofState.DISABLED,
            start_time=text_of(find(get[2], "Settings.StartTime")),
            end_time=text_of(find(get[2], "Settings.EndTime")),
            messages=messages,
        )

    @staticmethod
    def _oof_message(children: list[Node]) -> OofMessage:
        applies_to = next(
            (scope for scope, tag in _OOF_APPLIES_TO_TAGS.items() if find(children, f"Settings.{tag}") is not None),
            "",
        )
        return OofMessage(
            applies_to=applies_to,
            enabled=text_of(find(children, "Settings.Enabled")) == "1",
            reply_message=text_of(find(children, "Settings.ReplyMessage")),
            body_type=text_of(find(children, "Settings.BodyType")),
        )

    def set_oof(
        self,
        state: OofState,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        reply_message: str | None = None,
        body_type: str = "Text",
        applies_to: Iterable[str] = ("Internal", "ExternalKnown", "ExternalUnknown"),
    ) -> None:
        """``Settings`` Oof Set: enable/disable/schedule the Out-of-Office autoreply.

        ``start_time``/``end_time`` only apply with ``state=OofState.ENABLED_SCHEDULED``.
        If ``reply_message`` is given, it's sent identically as one
        ``OofMessage`` block per scope in ``applies_to`` -- EAS has no
        single "same message everywhere" shortcut. Unverified against a
        live server; see ``get_oof()``.
        """
        self._ensure_provisioned()
        set_children = [wtag("Settings", "OofState", text=str(int(state)))]
        if state == OofState.ENABLED_SCHEDULED:
            if start_time:
                set_children.append(wtag("Settings", "StartTime", text=start_time))
            if end_time:
                set_children.append(wtag("Settings", "EndTime", text=end_time))
        if reply_message is not None:
            for scope in applies_to:
                set_children.append(
                    wtag(
                        "Settings",
                        "OofMessage",
                        children=[
                            wtag("Settings", _OOF_APPLIES_TO_TAGS[scope]),
                            wtag("Settings", "Enabled", text="1"),
                            wtag("Settings", "ReplyMessage", text=reply_message),
                            wtag("Settings", "BodyType", text=body_type),
                        ],
                    ),
                )
        w = WBXMLWriter()
        w.tag(
            "Settings",
            "Settings",
            children=[wtag("Settings", "Oof", children=[wtag("Settings", "Set", children=set_children)])],
        )
        resp = self._post("Settings", w.render())
        nodes = WBXMLReader(resp).parse()
        _check_status("Settings", text_of(find(nodes, "Settings.Status")))
        oof = find(nodes, "Settings.Oof")
        if oof is not None:
            _check_status("Settings.Oof", text_of(find(oof[2], "Settings.Status")))
