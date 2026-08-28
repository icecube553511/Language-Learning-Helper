## Summary

- Describe the user-visible and architectural changes.

## Cross-platform checklist

- [ ] Windows behavior and tests are updated.
- [ ] Android behavior and tests are updated.
- [ ] A platform-only exception is explicitly documented, if applicable.
- [ ] Shared contracts and platform manifests are synchronized.
- [ ] Architecture boundaries in `ARCHITECTURE.md` and `AGENTS.md` are preserved.
- [ ] `python tools/verify_sync.py` passes.
- [ ] Windows unit tests and smoke test pass.
- [ ] Android `test lintDebug assembleDebug` passes with JDK 17.
