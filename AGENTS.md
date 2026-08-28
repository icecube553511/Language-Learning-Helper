# Repository Working Agreement

This is a synchronized Windows and Android product. Follow `ARCHITECTURE.md`
and keep dependencies directed from presentation to application to domain;
infrastructure implements inner ports and platform APIs stay at the edge.

For every behavior change:

- Implement Windows and Android in the same branch and pull request unless the
  request explicitly declares a platform-only exception.
- Put shared behavior in `shared/contracts/` first, update all three platform
  manifests, and extend `tools/verify_sync.py` when parity can be automated.
- Keep domain rules platform-independent and transient UI state out of
  persistence. Presentation must not read catalog or storage files directly.
- Add risk-proportionate tests on both platforms. Before handoff, run
  `python tools/verify_sync.py`, Windows unit tests and smoke test, and Android
  `test lintDebug assembleDebug` with JDK 17.
- Preserve unrelated worktree changes. Record implementation and verification
  in Git commits and a GitHub pull request; do not deliver unpushed feature work.

Generated catalog and branding artifacts must be changed through their source
tools. See `CLAUDE.md` and `CODEBASE_ONBOARDING.md` for commands and entry points.
