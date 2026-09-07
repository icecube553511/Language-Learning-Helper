## Summary

- Describe the user-visible and architectural changes.

## Cross-platform checklist

- [ ] I read `ARCHITECTURE.md` completely before implementation.
- [ ] Windows behavior and tests are updated.
- [ ] Android behavior and tests are updated.
- [ ] A platform-only exception is explicitly documented, if applicable.
- [ ] Shared contracts and platform manifests are synchronized.
- [ ] Architecture boundaries and state ownership are preserved; known debt was
      not extended.
- [ ] `python tools/verify_sync.py` passes.
- [ ] Windows unit tests and smoke test pass.
- [ ] Android `test lintDebug assembleDebug` passes with JDK 17.
