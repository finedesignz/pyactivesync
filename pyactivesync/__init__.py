"""pyactivesync: a Python client for Exchange ActiveSync (EAS / MS-ASCMD / MS-ASWBXML)."""
from __future__ import annotations

from .client import Client
from .exceptions import EASError, ProtocolError, ProvisionError, StatusError
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

__version__ = "0.1.0"

__all__ = [
    "Client",
    "EASError",
    "ProtocolError",
    "ProvisionError",
    "StatusError",
    "AttachmentInfo",
    "BodyType",
    "Contact",
    "ContactAddResult",
    "ContactChange",
    "ContactChangesResult",
    "EmailAddResult",
    "EmailChange",
    "EmailChangesResult",
    "FetchedItem",
    "FindItem",
    "FindResult",
    "Folder",
    "FolderType",
    "GalEntry",
    "ItemBody",
    "OofMessage",
    "OofSettings",
    "OofState",
    "PingResult",
    "Recipient",
    "SyncItem",
    "SyncResult",
    "__version__",
]
