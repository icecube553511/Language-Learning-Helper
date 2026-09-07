# Repository Working Agreement

## Mandatory startup

Before inspecting, changing, generating, testing, or committing repository
content, read `ARCHITECTURE.md` completely. Then read
`CODEBASE_ONBOARDING.md` and the shared contract(s) relevant to the task. Do
not begin implementation until the dependency rules, state ownership, and
cross-platform delivery requirements in those documents are understood.

## Architecture and parity

This is a synchronized Windows and Android product. Keep dependencies directed
inward from presentation to application to domain. Infrastructure implements
inner ports, and platform APIs remain at composition roots or other edge
adapters. Existing exceptions are documented in `ARCHITECTURE.md`; do not
extend them.

For every behavior change:

- Implement Windows and Android in the same branch and pull request unless the
  request explicitly declares a platform-only exception.
- Put shared semantics in `shared/contracts/` first. Update the shared parity
  manifest and both platform manifests, and extend `tools/verify_sync.py` when
  parity can be automated.
- Keep domain rules platform-independent and transient UI state out of
  persistence. Presentation must not read catalog or storage files directly.
- Add risk-proportionate tests on both platforms. Before handoff, run
  `python tools/verify_sync.py`, Windows unit tests and smoke test, and Android
  `test lintDebug assembleDebug` with JDK 17.
- Preserve unrelated worktree changes. Record implementation and verification
  in Git commits and a GitHub pull request; do not deliver unpushed feature
  work.

Generated catalog and branding artifacts must be changed through their source
tools. See `CLAUDE.md` and `CODEBASE_ONBOARDING.md` for exact commands and entry
points.
