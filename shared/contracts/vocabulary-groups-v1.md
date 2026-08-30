# Vocabulary Groups v1

Version: `vocabulary-groups-v1`. The vocabulary ("词库") library browser on Windows
and Android must present words as an ordered list of *groups* (词书), so that a
user entering the library first sees the groups and then drills into a group to
see its words. This contract is the single source of truth for how a word is
classified into a group, the canonical group order and display names, and the
word-list behavior once a group is selected. Transient group/selection state is
presentation-only and must never be persisted.

## Purpose

Today a user entering the library sees a flat list of every word. The desired
experience is: enter the library -> see the groups (全部, CET-4, CET-6, 中考/zk,
高考/gk, 自定义) -> tap a group -> see the words inside that group with the same
columns/rows, search, CSV import, batch-label and review-time features the flat
list has today. Existing vocabulary features are preserved; groups are an added
browsing layer, not a replacement of the word list.

## Canonical groups

The canonical group keys, display labels, and membership rules are:

| groupKey | Label (zh) | A word belongs when | the normalized membership set or case-folded tag set contains |
|---|---|---|---|
| `all` | 全部 | Always. Every entry belongs to this group. | n/a |
| `cet4` | CET-4（四级） | membership or tag | `CET4` / `cet4` |
| `cet6` | CET-6（六级） | membership or tag | `CET6` / `cet6` |
| `zk` | 中考（zk） | membership or tag | `ZK` / `zk` |
| `gk` | 高考（gk） | membership or tag | `GK` / `gk` |
| `custom` | 自定义 | membership | `CUSTOM` |

Classification algorithm (identical on both platforms):

1. Normalize the word's membership (level) set: for each value, apply Unicode
   NFKC, trim, strip spaces, and remove `-`, `_`, `.`, then uppercase. The
   result is the normalized membership set.
2. Normalize the word's tag set: apply Unicode NFKC, trim, then `casefold()` /
   `lowercase()`. The result is the normalized tag set.
3. A word belongs to `all` always. It belongs to `cet4`/`cet6`/`zk`/`gk` when
   the normalized membership set contains the matching canonical membership code
   (`CET4`/`CET6`/`ZK`/`GK`) OR the normalized tag set contains the matching
   lowercase tag (`cet4`/`cet6`/`zk`/`gk`). It belongs to `custom` when the
   normalized membership set contains `CUSTOM`.
4. A word may belong to several groups at once (for example a CET4 word tagged
   `gk` is in `cet4` and `gk`). There is no deduplication requirement across
   groups.

Only recognized group membership codes/tags create groups; arbitrary tags (for
example `business`) never create groups. Adding a future group means adding a row
to the canonical table above (or an extension version), implementing the same
predicate on both platforms, and extending `tools/verify_sync.py` and the golden
vector.

## Canonical order and empty groups

The presentation renders groups in this order, always including every canonical
group even when it currently has zero entries (the group card shows its live
count; a zero-count group opens to an empty-state):

```text
all -> cet4 -> cet6 -> zk -> gk -> custom
```

Any additional normalized membership code present in the library that is not one
of the canonical keys is appended after the canonical groups, ordered
alphabetically by code, with its code shown as the label. This keeps the browser
extensible as future catalogs or imports introduce new 词书.

## Word-list behavior once a group is selected

* Selecting a group shows exactly its member words in the unchanged word list
  (Windows `Treeview`, Android `LazyColumn`) with the same columns/rows, the
  1000-entry cap, the review-due column, CSV import, batch-label dialog and the
  search box.
* Searching while a group is selected filters within that group.
* When no group is selected (the browser view), typing a query searches the whole
  library, equivalent to `all`, preserving today's global search.
* A back/clear control returns to the group browser.
* Group-selection state is transient presentation state and is NOT persisted;
  reopening the library returns to the group browser.

## Golden vector

`vocabulary-groups-golden-v1.json` carries neutral fixtures plus the expected
per-group membership and counts. Both platforms must parse the fixtures into
their `VocabularyEntry` model (memberships -> level set, tags -> tag set) and
reproduce the expected `groupCounts` and per-fixture `expectedGroups` exactly
(group keys compared as sorted sets). A platform test must fail if its group
classifier diverges from the golden vector.

## Dictation manual word selection

The same group browser governs the "从词库选择" (manual) word selection on the
默写纸 (dictation worksheet). Entering manual selection shows the groups first;
tapping a group shows that group's eligible words in the existing selection
table, and a back control returns to the group browser. Group counts are
computed from the current dictation candidate pool (respecting the active 词库
level filters and the "包含已考察词" toggle). The group-selected state is
transient presentation state and is never persisted; the already-selected
word ids are kept across group switches.
