# Agent Team

LexiTrack uses a small team of focused roles to keep every behavior change
cross-platform and auditable. Roles work in sequence or, when the orchestrator
can run them, in parallel; they never touch overlapping files.

| Role | Scope | Owns |
|---|---|---|
| `architecture_audit` | Architecture, challenge & Windows | Challenge assumptions, enforce onion dependencies, and own Windows implementation/tests. |
| `pet_integration` | Android | Own Android domain/presentation integration and Android tests. |
| `sync_ci_audit` | Parity & delivery | Audit manifests, sync automation, Git state, GitHub PR overlap, and CI evidence. |
| root agent (orchestrator) | Cross-cutting | Own shared contracts/assets, resolve audit findings, run full verification, commit, push, and maintain the GitHub pull request. |

The team also owns the `petCompanionInteraction` capability. `architecture_audit` and
`pet_integration` may register platform UI bounds and render Bingzi, while the
orchestrator keeps the pet contract, source/derived assets, and parity markers
in sync.

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

## Confirmed cross-platform behaviors

Recorded in `CLAUDE.md` and `CODEBASE_ONBOARDING.md`. As of now they include:
review reminder auto-clearing from the dashboard, centered/enlarged review
start button, dictation row-click and drag-range multi-select, dictation
preview wheel paging, and the recursive word bubble fixes below.

## Current word-bubble cross-platform contract

The word bubble is governed by `shared/contracts/word-bubble-v1.md`. Open a
known word to see its Chinese meaning, part of speech, phonetic, and at least
three bilingual example pairs (English plus a Simplified-Chinese translation).
Unknown words fall back to “词库暂无中文释义”. Dismiss a bubble with its close
control to return to the parent; a root bubble is cleared entirely.
