# Changelog

## 0.1.1

- Installing through `install.sh` now turns on auto-update for the review-council marketplace, so new releases arrive on their own; `--no-auto-update` (or `REVIEW_COUNCIL_NO_AUTO_UPDATE=1`) opts out and leaves `settings.json` untouched.
- The plugin's version lives only in `plugins/review-council/.claude-plugin/plugin.json`; the marketplace entry no longer pins one, where it would silently have overridden the manifest.
- Opt-in update notice: with `check_updates: true` in the config, the session banner adds one line when a newer version is published. Off by default, cached for a day, and silent on any failure.

## 0.1.0

- Initial release: `/review-council:rev` multi-model review-and-fix loop and `/review-council:stack` cross-repo orchestrator, ported from the in-harness `rev` skill.
- Roster built at run time from whichever of the Codex, Grok, Gemini and Claude (Opus) seats are installed and signed in, instead of a hardcoded seat list.
- `SessionStart` hook injects the standing review policy and a one-line roster summary every session.
- Portable across macOS and Linux; shimmed unit test suite with no network access, run in CI on both platforms.
