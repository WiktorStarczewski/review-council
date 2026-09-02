# Changelog

## 0.1.0

- Initial release: `/review-council:rev` multi-model review-and-fix loop and `/review-council:stack` cross-repo orchestrator, ported from the in-harness `rev` skill.
- Roster built at run time from whichever of the Codex, Grok, Gemini and Claude (Opus) seats are installed and signed in, instead of a hardcoded seat list.
- `SessionStart` hook injects the standing review policy and a one-line roster summary every session.
- Portable across macOS and Linux; shimmed unit test suite with no network access, run in CI on both platforms.
