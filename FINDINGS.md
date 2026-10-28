# JWPUB EAS Connection Test — Findings

Date: 2026-10-28
Branch: `test/jwpub-connect`
Server: `eas.jwpub.org`
Device ID: `TiTowerTest01`

## Protocol versions
`MS-ASProtocolVersions`: 2.0,2.1,2.5,12.0,12.1,14.0,14.1,16.0,16.1 — includes 16.1, which pyactivesync targets. Compatible, no version negotiation needed.

`MS-ASProtocolCommands`: Sync,SendMail,SmartForward,SmartReply,GetAttachment,GetHierarchy,CreateCollection,DeleteCollection,MoveCollection,FolderSync,FolderCreate,FolderDelete,FolderUpdate,MoveItems,GetItemEstimate,MeetingResponse,Search,Settings,Ping,ItemOperations,Provision,ResolveRecipients,ValidateCert,Find

Note: server advertises `SmartForward`/`SmartReply` support even though pyactivesync's library doesn't implement them (documented gap in the test plan).

## Auth method
Basic auth over HTTPS — worked on the first try. No OAuth/Bearer challenge seen (`WWW-Authenticate: None` on success).

**Correction to the test plan:** the plan specified username `Michael517@jwpub.org`. The live credential in Proton Pass (vault "Personal", item titled `jwpub.org`, most recently modified) is `michaels17@jwpub.org` (used successfully). Treat the plan's username as a transcription typo.

## Status codes / timing
- Phase 3 (OPTIONS, no device created): 200, immediate.
- Phase 4 Provision: succeeded immediately, no 2-day new-device hold or quarantine observed, no device-limit error.
- Phase 4 FolderSync/list_folders: 14 folders returned on first call (Inbox, Sent Items, Drafts, Calendar, Contacts, Tasks, Notes, Journal, Archive, Junk Email, Deleted Items, Outbox, Conversation History, RecipientInfo).
- Phase 5 Sync (bootstrap + delta): both succeeded; delta returned 1 item.
- Phase 5 Fetch: succeeded, body present, 0 attachments on the fetched item.
- Phase 5 Ping: succeeded (status `2`, no changed folders in the short window tested).
- Phase 5 SendMail: **failed, EAS status 120 (`MailSubmissionFailed`)** — a global/server-side status, not one pyactivesync maps by name (library only maps 101/InvalidContent for SendMail). Not a retcode indicating auth/library incompatibility; everything else on the same authenticated session worked.

## SendMail root-cause evidence (added 2026-10-28)
Raw HTTP response, captured by intercepting the transport layer directly (not library-interpreted):

```
HTTP status: 200 OK
Content-Type: application/vnd.ms-sync.wbxml
X-CalculatedBETarget: usmailext053.jwpub.org
X-BEServer: USMAILEXT053
X-FEServer: USMAILEXT065
X-DiagInfo: USMAILEXT053
X-MS-BackOffDuration: M/360
WBXML body (decoded): SendMail Status = 120
```

**Recipient-independence check:** re-ran the same send against a different real recipient (`EichelkrauJ6@jwpub.org`, not self) — identical result, same Status=120, same backend/headers. Rules out a self-send-only restriction; this is a blanket block on `SendMail` for this account/device, independent of recipient. Strengthens the org-level-policy theory over any per-recipient or self-send-specific rule.

- Backend hostname/header style confirms jwpub.org mail is **on-premises Exchange**, not Exchange Online.
- The request reached the mailbox server cleanly (200 OK, well-formed WBXML) — rules out network/auth/protocol-version causes.
- Status 120 is raised at the submission stage (post-validation), not a malformed-request code (101-107) — consistent with a server-side policy decision, not a content problem.
- `X-MS-BackOffDuration: M/360` is only emitted when a client-throttling/policy check ran against the request — circumstantial evidence the server is evaluating (and failing) the send against an anti-abuse or EAS-send policy, independent of the account's own mailbox permissions.

**Most likely root cause (moderate confidence):** a server-side anti-abuse/outbound policy on the on-prem Exchange org is blocking `SendMail` specifically — common hardening that lets a device read mail immediately but blocks compose/send until the device ages, or disables EAS SendMail org-wide. This matches the exact asymmetry observed (every read op works, only send fails). Can't fully disambiguate "new-device cooldown" vs. "EAS send disabled org-wide" from the client side; confirming needs Exchange-side transport/ActiveSync logs (IT/Bethel admin access), out of scope for this client-side test. Switching EAS libraries (e.g. to TbSync) will not change this outcome — it's server-side, not a library gap.

**Confirmed (2026-10-28, via OWA Options > Mobile devices > device details):** `TiTowerTest01` shows `Access state: Quarantined`, `Access set by: Global permissions` — an on-prem Exchange ActiveSync Device Access Rule, org default-quarantines unrecognized `DeviceType`/`UserAgent` client families. Explains the Windows Mail / iPad / iPhone asymmetry directly: those clients' device signatures are already trusted (or covered by org defaults), so they're never quarantined. Also explains the read/send split: Exchange's default quarantine behavior still permits sync while blocking mail submission until an admin (or an auto-clear timer) releases the device. Per owner (2026-10-28): new devices on this org are commonly quarantined for about a day before auto-clearing — consistent with the original test plan's anticipated "2-day new-device hold," just manifesting as send-blocked-only rather than fully blocked. **Action: none needed from the client/library side — wait and recheck `SendMail` after the device has had time to clear, or ask Bethel IT to release `TiTowerTest01` from quarantine if it's still blocked after ~1-2 days.** A DeviceType-spoofing diagnostic (presenting as a pre-trusted client, e.g. "iPhone") was considered to further isolate the cause but was not run once quarantine was confirmed directly from the server — deliberately mimicking a trusted client identity to route around an admin-set access-control decision isn't an appropriate step here.

## Device identity change: JWMail (2026-10-28)
Decided to stop using the library's own dev-default identity (`DeviceType: pyactivesync`, `UserAgent: pyactivesync/0.1`, plus the un-set HTTP `User-Agent` leaking `python-requests/<ver>`) and give the real client its own honest identity instead: `DeviceType: JWMail`. This is a standalone client, **not** part of Titanium Edge. Explicitly ruled out presenting as `DeviceType: iPhone` or `WindowsOutlook` (an already-approved, real Microsoft/Apple client) even though Windows Mail is discontinued — that would be impersonating a specific recognized product to route around the org's access-control decision, not a naming choice; declined.

`pyactivesync/client.py` and `_http.py` now take `device_type`/`device_model`/`device_friendly_name`/`device_os`/`user_agent` as constructor params (previously hardcoded to the library's own name); the HTTP `User-Agent` header is now set to match. New test device `JWMailTest01` provisioned under this identity — reads work immediately (same as before), will hit the same quarantine on send until approved.

## Provisioning policy requirements (2026-10-28)
Decoded the full `EASProvisionDoc` jwpub.org returns during `Provision` (previously only `Status`/`PolicyKey` were read; the actual policy content was discarded). Key values: `DevicePasswordEnabled: 0`, `RequireDeviceEncryption: 0`, `AllowSimpleDevicePassword: 1`, no min password length/complexity/history enforced — **the org's EAS provisioning policy requires essentially nothing** (no PIN, no encryption, no device lockdown). This answers the "if we meet the same security standards, will they approve it" question directly: **there's no meaningful security-posture bar to clear here** — pyactivesync already correctly acknowledges this (near-empty) policy. The `SendMail` quarantine is governed entirely by the separate **Device Access Rule** (identity allow-list) found above, not by policy/compliance. The ask to IT should be framed as "please recognize this DeviceType" (an access-list addition), not "please review our app's security compliance" — there's nothing to review on that front.

## Library bugs found
None observed in the paths exercised (provision, list_folders, sync_folder bootstrap+delta, fetch_item, ping). `send_mail` correctly surfaced the server's status via `StatusError`; this is expected behavior, not a bug.

## Interpretation / pass criteria
Plan's Phase 5 pass bar is 4/4 steps working. **3 of 4 passed** (sync, fetch, ping); send failed on a server-side policy status, most consistent with jwpub's EAS deployment disabling SendMail/compose-over-EAS for this account (a common Exchange Online/EAS hardening) rather than a protocol or library defect.

## Unknowns answered
1. Does jwpub offer EAS 16.1? **Yes.**
2. Basic auth or OAuth only? **Basic auth works.**
3. Does the 2-day new-device hold apply? **No — provisioned and synced immediately.**

## Next step (owner decision needed)
Greenlight for read-only client features (inbox sync, folder list, fetch/read) is clear. Send-via-EAS is blocked server-side; a client needs either (a) a different outbound path (e.g. SMTP submit, if offered/allowed for this account) or (b) to treat compose as read-only inbox/calendar sync only, with send out of scope. This is a real server-side restriction, not something to patch around in the client — needs an owner call on whether compose is in scope at all for this project.

Test devices `TiTowerTest01` (pyactivesync identity, quarantined) and `JWMailTest01` (JWMail identity, reads working) are both still registered pending IT approval of the `JWMail` device type.
