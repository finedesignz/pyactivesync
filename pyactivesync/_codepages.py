"""MS-ASWBXML codepage token tables.

Token values are the real MS-ASWBXML codepage numbers, verified against
both the official spec
(https://learn.microsoft.com/en-us/openspecs/exchange_server_protocols/ms-aswbxml/)
and a live Exchange server -- not an arbitrary local enum order.
"""
from __future__ import annotations

CODEPAGES: dict[str, dict[str, int]] = {
    "AirSync": {
        "Sync": 0x05, "Responses": 0x06, "Add": 0x07, "Change": 0x08,
        "Delete": 0x09, "Fetch": 0x0A, "SyncKey": 0x0B, "ClientId": 0x0C,
        "ServerId": 0x0D, "Status": 0x0E, "Collection": 0x0F, "Class": 0x10,
        "Version": 0x11, "CollectionId": 0x12, "GetChanges": 0x13,
        "MoreAvailable": 0x14, "WindowSize": 0x15, "Commands": 0x16,
        "Options": 0x17, "FilterType": 0x18, "Truncation": 0x19,
        "Conflict": 0x1B, "Collections": 0x1C, "ApplicationData": 0x1D,
        "DeletesAsMoves": 0x1E, "Supported": 0x20, "SoftDelete": 0x21,
        "MIMESupport": 0x22, "MIMETruncation": 0x23, "Wait": 0x24,
        "Limit": 0x25, "Partial": 0x26, "MaxItems": 0x28,
        "HeartbeatInterval": 0x29,
    },
    # Contacts token values are taken verbatim from the official MS-ASWBXML
    # spec (code page 1), not reverse-engineered.
    "Contacts": {
        "Anniversary": 0x05, "AssistantName": 0x06, "AssistantPhoneNumber": 0x07,
        "Birthday": 0x08, "Business2PhoneNumber": 0x0C,
        "BusinessAddressCity": 0x0D, "BusinessAddressCountry": 0x0E,
        "BusinessAddressPostalCode": 0x0F, "BusinessAddressState": 0x10,
        "BusinessAddressStreet": 0x11, "BusinessFaxNumber": 0x12,
        "BusinessPhoneNumber": 0x13, "CarPhoneNumber": 0x14,
        "Categories": 0x15, "Category": 0x16, "CompanyName": 0x19,
        "Department": 0x1A, "Email1Address": 0x1B, "Email2Address": 0x1C,
        "Email3Address": 0x1D, "FileAs": 0x1E, "FirstName": 0x1F,
        "Home2PhoneNumber": 0x20, "HomeAddressCity": 0x21,
        "HomeAddressCountry": 0x22, "HomeAddressPostalCode": 0x23,
        "HomeAddressState": 0x24, "HomeAddressStreet": 0x25,
        "HomeFaxNumber": 0x26, "HomePhoneNumber": 0x27, "JobTitle": 0x28,
        "LastName": 0x29, "MiddleName": 0x2A, "MobilePhoneNumber": 0x2B,
        "OfficeLocation": 0x2C, "OtherAddressCity": 0x2D,
        "OtherAddressCountry": 0x2E, "OtherAddressPostalCode": 0x2F,
        "OtherAddressState": 0x30, "OtherAddressStreet": 0x31,
        "PagerNumber": 0x32, "RadioPhoneNumber": 0x33, "Spouse": 0x34,
        "Suffix": 0x35, "Title": 0x36, "WebPage": 0x37,
    },
    "Email": {
        "DateReceived": 0x0F, "DisplayTo": 0x11, "Importance": 0x12,
        "MessageClass": 0x13, "Subject": 0x14, "Read": 0x15, "To": 0x16,
        "Cc": 0x17, "From": 0x18, "ReplyTo": 0x19, "Categories": 0x1B,
        "Category": 0x1C, "InternetCPID": 0x39, "Flag": 0x3A,
        "Status": 0x3B, "ContentClass": 0x3C, "FlagType": 0x3D,
        "CompleteTime": 0x3E,
    },
    "Tasks": {
        "DateCompleted": 0x0B, "DueDate": 0x0C, "UtcDueDate": 0x0D,
        "ReminderSet": 0x1B, "ReminderTime": 0x1C,
        "StartDate": 0x1E, "UtcStartDate": 0x1F, "Subject": 0x20,
        "OrdinalDate": 0x22,
    },
    "Move": {
        "MoveItems": 0x05, "Move": 0x06, "SrcMsgId": 0x07, "SrcFldId": 0x08,
        "DstFldId": 0x09, "Response": 0x0A, "Status": 0x0B, "DstMsgId": 0x0C,
    },
    "ItemEstimate": {
        "GetItemEstimate": 0x05, "Collections": 0x07, "Collection": 0x08,
        "CollectionId": 0x0A, "Estimate": 0x0C, "Response": 0x0D, "Status": 0x0E,
    },
    "FolderHierarchy": {
        "DisplayName": 0x07, "ServerId": 0x08, "ParentId": 0x09,
        "Type": 0x0A, "Response": 0x0B, "Status": 0x0C, "Changes": 0x0E,
        "Add": 0x0F, "Delete": 0x10, "Update": 0x11, "SyncKey": 0x12,
        "FolderCreate": 0x13, "FolderDelete": 0x14, "FolderUpdate": 0x15,
        "FolderSync": 0x16, "Count": 0x17,
    },
    "Provision": {
        "Provision": 0x05, "Policies": 0x06, "Policy": 0x07,
        "PolicyType": 0x08, "PolicyKey": 0x09, "Data": 0x0A,
        "Status": 0x0B, "RemoteWipe": 0x0C, "EASProvisionDoc": 0x0D,
    },
    "Ping": {
        "Ping": 0x05, "AutdState": 0x06, "Status": 0x07, "HeartbeatInterval": 0x08,
        "Folders": 0x09, "Folder": 0x0A, "Id": 0x0B, "Class": 0x0C, "MaxFolders": 0x0D,
    },
    "AirSyncBase": {
        "BodyPreference": 0x05, "Type": 0x06, "TruncationSize": 0x07, "AllOrNone": 0x08,
        "Body": 0x0A, "Data": 0x0B, "EstimatedDataSize": 0x0C, "Truncated": 0x0D,
        "Attachments": 0x0E, "Attachment": 0x0F, "DisplayName": 0x10, "FileReference": 0x11,
        "Method": 0x12, "ContentId": 0x13, "ContentLocation": 0x14, "IsInline": 0x15,
        "NativeBodyType": 0x16, "ContentType": 0x17, "Preview": 0x18,
    },
    "Settings": {
        "Settings": 0x05, "Status": 0x06, "Get": 0x07, "Set": 0x08,
        "Oof": 0x09, "OofState": 0x0A, "StartTime": 0x0B, "EndTime": 0x0C,
        "OofMessage": 0x0D, "AppliesToInternal": 0x0E, "AppliesToExternalKnown": 0x0F,
        "AppliesToExternalUnknown": 0x10, "Enabled": 0x11, "ReplyMessage": 0x12,
        "BodyType": 0x13,
        "DeviceInformation": 0x16, "Model": 0x17, "IMEI": 0x18,
        "FriendlyName": 0x19, "OS": 0x1A, "OSLanguage": 0x1B,
        "PhoneNumber": 0x1C, "UserAgent": 0x20,
    },
    "ItemOperations": {
        "ItemOperations": 0x05, "Fetch": 0x06, "Store": 0x07, "Options": 0x08,
        "Range": 0x09, "Total": 0x0A, "Properties": 0x0B, "Data": 0x0C,
        "Status": 0x0D, "Response": 0x0E, "Version": 0x0F, "Schema": 0x10,
        "Part": 0x11,
    },
    "ComposeMail": {
        "SendMail": 0x05, "SmartForward": 0x06, "SmartReply": 0x07,
        "SaveInSentItems": 0x08, "ReplaceMime": 0x09, "Source": 0x0B,
        "FolderId": 0x0C, "ItemId": 0x0D, "LongId": 0x0E,
        "InstanceId": 0x0F, "MIME": 0x10, "ClientId": 0x11,
        "Status": 0x12, "AccountId": 0x13,
    },
    # ResolveRecipients/Search/GAL token values are taken verbatim from the
    # official MS-ASWBXML spec, not reverse-engineered.
    "ResolveRecipients": {
        "ResolveRecipients": 0x05, "Response": 0x06, "Status": 0x07, "Type": 0x08,
        "Recipient": 0x09, "DisplayName": 0x0A, "EmailAddress": 0x0B,
        "Certificates": 0x0C, "Certificate": 0x0D, "MiniCertificate": 0x0E,
        "Options": 0x0F, "To": 0x10, "CertificateRetrieval": 0x11,
        "RecipientCount": 0x12, "MaxCertificates": 0x13, "MaxAmbiguousRecipients": 0x14,
        "CertificateCount": 0x15,
    },
    "Search": {
        "Search": 0x05, "Store": 0x07, "Name": 0x08, "Query": 0x09,
        "Options": 0x0A, "Range": 0x0B, "Status": 0x0C, "Response": 0x0D,
        "Result": 0x0E, "Properties": 0x0F, "Total": 0x10,
        "EqualTo": 0x11, "Value": 0x12, "And": 0x13, "Or": 0x14, "FreeText": 0x15,
        "DeepTraversal": 0x17, "LongId": 0x18, "RebuildResults": 0x19,
        # GreaterThan verified byte-for-byte against a captured, working
        # request/response pair (Store.Status=1, Total=96). Note
        # Class/CollectionId scoping inside a Search query uses the
        # *AirSync* codepage's tokens (xmlns="AirSync" in the spec XML),
        # not tokens on this page -- do not add Search.Class/CollectionId.
        "GreaterThan": 0x1B,
    },
    "GAL": {
        "DisplayName": 0x05, "Phone": 0x06, "Office": 0x07, "Title": 0x08,
        "Company": 0x09, "Alias": 0x0A, "FirstName": 0x0B, "LastName": 0x0C,
        "HomePhone": 0x0D, "MobilePhone": 0x0E, "EmailAddress": 0x0F,
    },
    # Find is codepage 25 and is available only in EAS 16.1.  In particular,
    # Options is a child of the search criterion, not ExecuteSearch; Exchange
    # rejects the latter (used by some older clients) with Status=2.
    "Find": {
        "Find": 0x05, "SearchId": 0x06, "ExecuteSearch": 0x07,
        "MailBoxSearchCriterion": 0x08, "Query": 0x09, "Status": 0x0A,
        "FreeText": 0x0B, "Options": 0x0C, "Range": 0x0D,
        "DeepTraversal": 0x0E, "Response": 0x11, "Result": 0x12,
        "Properties": 0x13, "Preview": 0x14, "HasAttachments": 0x15,
        "Total": 0x16, "DisplayCc": 0x17, "DisplayBcc": 0x18,
        "GALSearchCriterion": 0x19, "MaxPictures": 0x1A,
        "MaxSize": 0x1B, "Picture": 0x1C,
    },
}

# Real MS-ASWBXML codepage numbers (must match the protocol, not an
# arbitrary local order -- these are the values sent in SWITCH_PAGE).
PAGE_INDEX: dict[str, int] = {
    "AirSync": 0,
    "Contacts": 1,
    "Email": 2,
    "Move": 5,
    "ItemEstimate": 6,
    "FolderHierarchy": 7,
    "Tasks": 9,
    "Ping": 13,
    "Provision": 14,
    "ResolveRecipients": 10,
    "Search": 15,
    "GAL": 16,
    "AirSyncBase": 17,
    "Settings": 18,
    "ItemOperations": 20,
    "ComposeMail": 21,
    "Find": 25,
}

PAGE_ORDER: dict[int, str] = {num: name for name, num in PAGE_INDEX.items()}

REVERSE: dict[int, dict[int, str]] = {
    PAGE_INDEX[page]: {tok & 0x3F: tag for tag, tok in tags.items()}
    for page, tags in CODEPAGES.items()
}
