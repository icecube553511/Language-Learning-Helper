# Agent Team

LexiTrack uses a small team of focused roles to keep every behavior change
cross-platform and auditable. Roles work in sequence or, when the orchestrator
can run them, in parallel; they never touch overlapping files.

| Role | Scope | Owns |
|---|---|---|
| `windows_implementation` | Windows | Audit and own Windows domain/application/infrastructure/presentation changes and tests. |
| `android_implementation` | Android | Audit and own Android domain/application/infrastructure/presentation changes and tests. |
| `contract_delivery` | Parity & delivery | Audit manifests, sync automation, Git state, GitHub PR overlap, and CI evidence. |
| `grilling_review` | Requirements | Challenge ambiguous boundaries, defaults, ordering, persistence, failures, and interaction details before implementation. |
| root agent (orchestrator) | Cross-cutting | Own shared contracts/assets, resolve audit findings, run full verification, commit, push, and maintain the GitHub pull request. |

The team owns `petCompanionInteraction` and `petVitalsAndRatingRewards`.
Platform roles register UI bounds, render Bingzi, and implement their client;
the orchestrator keeps contracts, source/derived assets, parity markers, and
delivery evidence synchronized.

## Rules

- Shared semantics live in `shared/contracts/` before any platform code. Each
  contract change is mirrored in `tools/verify_sync.py` when it is automatable.
- Every behavior change lands on Windows **and** Android in the same commit and
  PR, plus shared contracts, tests, and docs. Platform-only changes require an
  explicit exception in the request.
- Platform agents never write to `shared/` or to each other's
  directories. The orchestrator owns shared resources and treats them read-only
  for the platform roles.
- Before handoff run, in order: `python tools/verify_sync.py`, Windows unit
  tests and the smoke test, and Android `test lintDebug assembleDebug` with
  JDK 17. Then commit and open the GitHub pull request so the work is traceable.

For `pet-vitals-v1`, movement `PetState` remains transient while vitals and the
single recovery marker are persisted through inner ports. The marker is never
a vocabulary tag. Reward-flight instances, trails, and burst particles remain
presentation-only and each accepted activation creates an independent instance.

## Confirmed cross-platform behaviors

Recorded in `CLAUDE.md` and `CODEBASE_ONBOARDING.md`. As of now they include:
review reminder auto-clearing from the dashboard, centered/enlarged review
start button, dictation row-click and drag-range multi-select, dictation
preview wheel paging, the recursive word bubble fixes below, and the library
group browser (`vocabulary-groups-v1`): entering 词库 shows the wordbook groups
first (全部, CET-4, CET-6, 中考/zk, 高考/gk, 自定义), then a group opens its words
while preserving all existing library features. The same layering applies to
the 默写纸, whose former top 四级/六级/自定义 checkboxes are removed; the group
browser is the single scope chooser for both 随机填写 (tap a group/all to set
the sample scope and inspect its words read-only, with an explicit handoff to
manual selection) and 从词库选择 (open a group to tick its words, persisting
selections across groups). Both platforms also render the transient dictation
entry loader as a visibly turning book page rather than a spinner or static icon.

## Current word-bubble cross-platform contract

The word bubble is governed by `shared/contracts/word-bubble-v1.md`. Open a
known word to see its Chinese meaning, part of speech, phonetic, and at least
three bilingual example pairs (English plus a Simplified-Chinese translation).
Unknown words fall back to “词库暂无中文释义”. Dismiss a bubble with its close
control to return to the parent; a root bubble is cleared entirely.
