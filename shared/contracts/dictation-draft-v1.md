# Dictation draft and optional sync v1

Version: `dictation-draft-v1`

This contract defines the persisted editor draft for the Windows and Android
默写纸 screens. It is separate from the printable `Document` model and from
learning progress.

## Draft shape

The persisted editor object is a single canonical JSON object. It contains
the following keys (keys with a null value are still emitted):

```json
{
  "version": 1,
  "mode": "random",
  "scopeGroup": "all",
  "openGroup": null,
  "count": 10,
  "includeEvaluated": false,
  "formats": ["DOCX", "PDF"],
  "fontSizePt": 12,
  "missingFields": ["word"],
  "showInitial": false,
  "includeExamples": false,
  "includeExampleChinese": false,
  "customExample": "",
  "selectedIds": [],
  "groups": {},
  "rangeEnabled": true,
  "syncMetadata": {
    "accountId": "",
    "revision": "0",
    "updatedAtUtc": 0.0,
    "deleted": false
  }
}
```

Each `groups` value contains `selectedIds`, nullable `anchorId`, nullable
`endpointId`, a normalized `scrollPosition` in `0..1`, and `expanded`. IDs
are normalized with Unicode NFKC, trim, and casefold before de-duplication;
group keys are lower-case canonical keys. Row numbers and pixel coordinates
are never stored. `syncMetadata` is part of the local record so local and
remote canonical hashes are identical. A transport envelope is the same
metadata plus either this draft or `null` when `deleted=true`:

```json
{
  "accountId": "user-1",
  "revision": "42",
  "updatedAtUtc": 1730000000.0,
  "deleted": false,
  "draft": { "...": "canonical draft object" }
}
```

A deleted envelope is a tombstone and must not be silently replaced by an
older draft. Implementations must reject a canonical draft or envelope larger
than `1048576` UTF-8 bytes before attempting transport.

### Canonical sync types

The platform application layer exposes a `DictationDraftSyncPort`. Its domain
value types are `DictationDraftSyncMetadata` and
`DictationDraftSyncEnvelope`; the metadata fields map to the JSON names above
(`accountId`, `revision`, `updatedAtUtc`, and `deleted`). `revision` is an
opaque server token. An empty revision is the initial local value and is sent
without an `If-Match` header; clients must compare revisions for equality and
must not infer ordering from the token text.

Pull and push return a result status. The required statuses are `disabled`
(local-only/no request), `synced`, `conflict`, `tombstone`, and `too-large`.
`conflict` retains both local and remote envelopes for an explicit user
choice. A `tombstone` has `deleted=true` and `draft=null`; receiving one with a
different revision is a conflict rather than an implicit local delete.

Canonical JSON is compact UTF-8 JSON with lexicographically sorted object keys,
no insignificant whitespace, and no non-finite numbers. ID normalization is
applied before encoding (Unicode NFKC, trim, casefold, then de-duplicate).
The byte limit is measured on the complete envelope bytes, including metadata.

## Restore

Unknown or deleted IDs are discarded. IDs that remain valid are retained even
if their current group changed; the latest group classifier determines where
they are shown. An anchor or endpoint that is no longer valid for its group is
cleared (and an endpoint is cleared whenever its anchor is cleared). Scroll
positions are clamped to the current list bounds. New words are never
auto-selected.

## Optional online transport

Clients may implement `GET/PUT /v1/dictation-drafts/{accountId}` over HTTPS
with a Bearer token. `PUT` includes `If-Match: <revision>`; a revision mismatch
returns a conflict and neither side may be silently overwritten. The client
keeps at most the current draft, the last synced envelope, and three conflict
backups. When the user chooses a side, the unchosen envelope (including a
tombstone) is added newest-first to an encrypted local ring. Canonically
identical backups are de-duplicated and the oldest entry is dropped when the
ring exceeds three entries. Failure to persist the unchosen envelope must
leave the conflict unresolved rather than overwrite either side. A canonical
UTF-8 JSON payload over `1 MiB` disables sync for that attempt but does not
block local persistence.

The service is optional. Missing endpoint, account, or credential means local
only mode and the sync port must report `disabled` without making a network
request. Vocabulary packages referenced by a remote draft are separate
versioned imports and require explicit user confirmation before using the
existing CSV/catalog validation path. Access tokens are supplied by the
composition root/platform secure storage and are never written to the draft,
ordinary preferences, or logs.
