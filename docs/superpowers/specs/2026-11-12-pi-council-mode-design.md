# Pi Council session mode

## Intent

Show the selected Council panel in Pi and use it for every new Council review in the session, whether requested by command or conversationally.

## Approaches

Extend the existing Council extension (selected): native footer status, command handling and session entries, matching the established Ponytail interaction without depending on Ponytail. A separate extension would split ownership and require extra installation. A Ponytail modification would make Council depend on an unrelated package and is rejected.

## Approved design

- Council owns its native `setStatus` key. The indicator remains visible without Ponytail installed.
- Display `⚖  council: 🌿 ECO` or `⚖  council: 🔥 HIGH`, with exactly two spaces between the scales icon and `council`, matching the requested Ponytail-style separation.
- `/council [scope and options]` starts a review, including bare `/council`.
- Exact `/council eco` and `/council high` set the session mode without a provider call; autocomplete offers these values. `/council status` reports it without starting a review.
- Default ECO maps to the existing normal preset: four Luna seats. HIGH maps to the existing high preset: Opus, Sol, Sonnet and Luna. Keep installed effort, substitution and recovery rules.
- Save selection as a custom session entry; restore on reload, resume, fork and tree navigation. A new session defaults to ECO.
- Inject the selected mode into agent context so conversational and direct-skill reviews receive the same default, not only slash-command reviews. Use existing panel-request parsing, not a new roster engine.
- A deliberate explicit per-review roster/mode overrides the session default for that review without changing the saved selection. An already-initialized review keeps its frozen roster.
- Keep `/rev` as a compatibility alias using the same handler. This is an implementation recommendation, not a request to remove existing workflows.

## Constraints and non-goals

No Ponytail imports, new dependencies, global roster-config writes, automatic reviews on mode changes, active-review mutation, new provider transports or changes to other hosts. Preserve scope text as data, existing busy/nested protection and help/setup diagnostics. Update Pi documentation and focused extension tests. Verify the footer through real Pi rendering before claiming visual completion; report unavailable verification explicitly.
