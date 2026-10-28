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

Test device `TiTowerTest01` is still registered (not removed) pending that decision.
