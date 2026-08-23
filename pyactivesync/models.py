"""Public data types returned by :class:`pyactivesync.client.Client`."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class FolderType(IntEnum):
    """MS-ASCMD ``FolderHierarchy:Type`` values."""

    GENERIC = 1
    INBOX = 2
    DRAFTS = 3
    DELETED_ITEMS = 4
    SENT_ITEMS = 5
    OUTBOX = 6
    TASKS = 7
    CALENDAR = 8
    CONTACTS = 9
    NOTES = 10
    JOURNAL = 11
    USER_GENERIC = 12
    USER_MAIL = 13
    USER_CALENDAR = 14
    USER_CONTACTS = 15
    USER_TASKS = 16
    USER_JOURNAL = 17
    USER_NOTES = 18
    UNKNOWN = 19
    RECIPIENT_CACHE = 20


class BodyType(IntEnum):
    """MS-ASAIRSYNCBASE ``BodyPreference:Type`` / ``Body:Type`` values."""

    PLAIN_TEXT = 1
    HTML = 2
    RTF = 3
    MIME = 4


class OofState(IntEnum):
    """MS-ASCMD ``Settings:Oof:OofState`` values."""

    DISABLED = 0
    ENABLED = 1
    ENABLED_SCHEDULED = 2


@dataclass(frozen=True, slots=True)
class Folder:
    id: str
    parent_id: str
    type: FolderType
    name: str


@dataclass(frozen=True, slots=True)
class SyncItem:
    """One ``Add`` or ``Change`` entry from a ``Sync`` response.

    ``fields`` is a flat ``{tag_name: text}`` dump of every leaf element
    under ``ApplicationData`` (e.g. ``"Email.Subject"``), so it works
    across Email/Contacts/Calendar item classes without a per-class field
    table.
    """

    server_id: str
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SyncResult:
    sync_key: str
    added: list[SyncItem] = field(default_factory=list)
    changed: list[SyncItem] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    more_available: bool = False


@dataclass(frozen=True, slots=True)
class EmailChange:
    """One client-originated email mutation sent through ``Sync``.

    ``None`` means leave that property unchanged. A delete cannot be combined
    with read or flag changes.
    """

    server_id: str
    read: bool | None = None
    flagged: bool | None = None
    delete: bool = False


@dataclass(frozen=True, slots=True)
class EmailChangesResult:
    """Result of applying one batch of email changes.

    EAS commonly omits per-item responses for successful changes. ``statuses``
    therefore starts at success (``"1"``) for every requested item and is
    overwritten by any explicit status returned by the server.
    """

    sync_key: str
    statuses: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EmailAddResult:
    """Result of creating one draft email with client-originated ``Sync Add``.

    ``server_id`` is present on success.  A rejected item still advances the
    collection synchronization key and is returned with its per-item status.
    """

    sync_key: str
    client_id: str
    status: str
    server_id: str | None = None


@dataclass(frozen=True, slots=True)
class Contact:
    """Writable MS-ASCONTACTS fields for one contact.

    Every field is optional and maps 1:1 to a ``Contacts`` codepage tag.
    Only fields set to a non-``None`` value (or a non-empty ``categories``)
    are sent to the server.

    Live testing against a real Exchange server showed a contact ``Sync
    Change`` does *not* merge: properties omitted from the ``ApplicationData``
    sent on an update were cleared server-side, not left untouched (confirmed
    by fetching the item after an update that set only ``job_title`` --
    ``first_name``/``last_name``/``company_name`` set at creation were gone).
    Pass the full desired field set to :meth:`~pyactivesync.client.Client.apply_contact_changes`
    on every update, not just the fields that changed.
    """

    first_name: str | None = None
    middle_name: str | None = None
    last_name: str | None = None
    suffix: str | None = None
    title: str | None = None
    job_title: str | None = None
    file_as: str | None = None
    company_name: str | None = None
    department: str | None = None
    office_location: str | None = None
    email1_address: str | None = None
    email2_address: str | None = None
    email3_address: str | None = None
    home_phone_number: str | None = None
    home2_phone_number: str | None = None
    business_phone_number: str | None = None
    business2_phone_number: str | None = None
    mobile_phone_number: str | None = None
    business_fax_number: str | None = None
    home_fax_number: str | None = None
    pager_number: str | None = None
    car_phone_number: str | None = None
    radio_phone_number: str | None = None
    assistant_name: str | None = None
    assistant_phone_number: str | None = None
    business_address_street: str | None = None
    business_address_city: str | None = None
    business_address_state: str | None = None
    business_address_postal_code: str | None = None
    business_address_country: str | None = None
    home_address_street: str | None = None
    home_address_city: str | None = None
    home_address_state: str | None = None
    home_address_postal_code: str | None = None
    home_address_country: str | None = None
    other_address_street: str | None = None
    other_address_city: str | None = None
    other_address_state: str | None = None
    other_address_postal_code: str | None = None
    other_address_country: str | None = None
    web_page: str | None = None
    spouse: str | None = None
    birthday: str | None = None
    anniversary: str | None = None
    categories: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContactAddResult:
    """Result of creating one contact with client-originated ``Sync Add``.

    ``server_id`` is present on success. A rejected item still advances the
    collection synchronization key and is returned with its per-item status.
    """

    sync_key: str
    client_id: str
    status: str
    server_id: str | None = None


@dataclass(frozen=True, slots=True)
class ContactChange:
    """One client-originated contact mutation sent through ``Sync``.

    Set ``contact`` for an update, or ``delete=True`` to remove the
    contact. Not both. See :class:`Contact` -- against a real Exchange
    server, an update replaces rather than merges, so ``contact`` should
    carry the full desired field set, not just what changed.
    """

    server_id: str
    contact: Contact | None = None
    delete: bool = False


@dataclass(frozen=True, slots=True)
class ContactChangesResult:
    """Result of applying one batch of contact changes.

    EAS commonly omits per-item responses for successful changes.
    ``statuses`` therefore starts at success (``"1"``) for every requested
    item and is overwritten by any explicit status returned by the server.
    """

    sync_key: str
    statuses: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AttachmentInfo:
    """One attachment from a fetched item's ``Attachments`` container.

    Use ``file_reference`` with ``Client.fetch_attachment()`` to download
    the actual bytes.
    """

    display_name: str | None
    file_reference: str
    method: int | None = None
    content_type: str | None = None
    estimated_data_size: int | None = None
    content_id: str | None = None
    content_location: str | None = None
    is_inline: bool = False


@dataclass(frozen=True, slots=True)
class ItemBody:
    """One ``AirSyncBase:Body`` returned by ``ItemOperations``.

    MIME (type 4) data is always exposed as bytes. Other body types normally
    contain text, but bytes are retained if the server used WBXML OPAQUE data.
    """

    type: BodyType
    data: str | bytes | None = None
    estimated_data_size: int | None = None
    truncated: bool | None = None
    part: str | None = None
    preview: str | None = None


@dataclass(frozen=True, slots=True)
class FetchedItem:
    """Lossless structured result of ``Client.fetch_item()``.

    ``fields`` contains non-body, non-attachment scalar properties. Repeated
    bodies and attachments retain their response order in dedicated lists.
    """

    fields: dict[str, str] = field(default_factory=dict)
    bodies: list[ItemBody] = field(default_factory=list)
    attachments: list[AttachmentInfo] = field(default_factory=list)
    native_body_type: BodyType | None = None
    content_type: str | None = None

    @property
    def body(self) -> ItemBody | None:
        """The first returned body, for the common one-body response."""
        return self.bodies[0] if self.bodies else None


@dataclass(frozen=True, slots=True)
class GalEntry:
    display_name: str | None = None
    email_address: str | None = None
    phone: str | None = None
    office: str | None = None
    title: str | None = None
    company: str | None = None
    alias: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    home_phone: str | None = None
    mobile_phone: str | None = None


@dataclass(frozen=True, slots=True)
class FindItem:
    """One result returned by the EAS 16.1 ``Find`` command.

    Mailbox results normally have both ids. GAL results have neither. All
    returned properties are preserved as dotted WBXML names in ``fields``.
    """

    server_id: str | None = None
    collection_id: str | None = None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FindResult:
    """One page of EAS 16.1 ``Find`` results.

    ``total`` is the number of items actually present in this response page,
    not the server's advisory ``Find:Total`` value.
    """

    search_id: str
    status: str
    range: str | None = None
    total: int = 0
    items: list[FindItem] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Recipient:
    type: str | None
    display_name: str | None
    email_address: str | None


@dataclass(frozen=True, slots=True)
class PingResult:
    status: str
    changed_folder_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class OofMessage:
    """One scope of an Out-of-Office autoreply (``Settings:Oof:OofMessage``).

    ``applies_to`` is one of ``"Internal"``, ``"ExternalKnown"``,
    ``"ExternalUnknown"``, mirroring which of the three
    ``AppliesTo*`` marker tags was present.
    """

    applies_to: str
    enabled: bool
    reply_message: str | None = None
    body_type: str | None = None


@dataclass(frozen=True, slots=True)
class OofSettings:
    state: OofState
    start_time: str | None = None
    end_time: str | None = None
    messages: list[OofMessage] = field(default_factory=list)
