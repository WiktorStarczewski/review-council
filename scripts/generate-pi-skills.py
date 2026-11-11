#!/usr/bin/env python3
"""Generate the Pi review contract from the canonical external-CLI workflow."""
import argparse
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / 'plugins/review-council'
SOURCE = PLUGIN / 'codex-skills/rev'
DEST = PLUGIN / 'pi-skills/review-council-rev'


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError('canonical workflow changed; update Pi binding: ' + before[:80])
    return text.replace(before, after, 1)


def generate(relative, text):
    text = text.replace('REVIEW_COUNCIL_HOST=codex', 'REVIEW_COUNCIL_HOST=pi')
    text = text.replace('${REVIEW_COUNCIL_HOST:-codex}', '${REVIEW_COUNCIL_HOST:-pi}')
    if relative == Path('SKILL.md'):
        text = replace_once(text, 'name: rev\n', 'name: review-council-rev\n')
        text = replace_once(text, '# Review Council for Codex', '# Review Council for Pi')
        start = text.index('When this skill is invoked from a conversation')
        end = text.index('\n## Mechanical phases', start)
        text = text[:start] + '''Pi core has no standard subagent tool. Own the review in this session; do not
launch another host as orchestrator or invent Agent/Task/Monitor calls. If an
installed subagent tool is available, a fresh orchestrator may use it, but it must
load this exact Pi skill and keep the same runtime and host binding. Never stop
just because a CLI command completed: inspect its output and continue the next
phase. A user pause or explicit external blocker is the only early stop.

For resumption, run `REVIEW_COUNCIL_HOST=pi python3 "$PLUGIN/scripts/rev-brief.py"
"$S" --host pi`, then read the returned `phase_file` relative to this skill.
Use Pi's `read`, `bash`, `edit`, and `write` tools. Shell exports do not persist
between tool calls: prefix every runtime command with `REVIEW_COUNCIL_HOST=pi`,
including workhorse, prompt, evidence, state, status and mechanical commands.
No native Agent reviewer or workhorse exists on Pi; an `agent` adapter is an
invalid host configuration, not permission to synthesize reviewer coverage.

## Pi process ownership

Pi bash has no persistent attached execution handle. Launch long provider calls
with stdin and both output streams redirected to session-owned files, retaining
the wrapper PID under its exact seat and label. Run from `REV_ROOT`:

```bash
rm -f "$S/r$ROUND-$SEAT.exit"
(
  REVIEW_COUNCIL_HOST=pi REV_REPO="$REV_ROOT" "$PLUGIN/scripts/rev-seat.sh" \\
    "$SEAT" "$S" "$ROUND" "$PROMPT" --base "$REV_BASE"
) >"$S/r$ROUND-$SEAT.launch.log" 2>&1 < /dev/null &
printf '%s\\n' "$!" >"$S/r$ROUND-$SEAT.pid"
```

Omit `--base` for documents. `rev-seat.sh` owns the exit marker and evidence;
never fabricate them. Inspect its exit/result/audit and logs at most 30 seconds
apart while pending; sleep in bounded bash calls between polls. Missing exit
markers require checking the recorded process identity and logs, not assuming
success. Apply the canonical retry/replacement path only after a terminal result.
Use the same session-owned redirection and polling for workhorse and status-watch
processes. Stop only processes this review owns; verify PID start identity before
signalling and preserve streams and valid siblings. Relay each narrated ten-minute
status line. Stay in the active turn until the authorized workflow is terminal or
there is a concrete external blocker. Do not edit while reviewer reads are active.
''' + text[end:]
        text = text.replace('including Codex and Claude Code', 'including Pi, Codex and Claude Code')
    if relative == Path('phases/10-setup.md'):
        text = text.replace('Codex roster', 'Pi roster')
    if relative == Path('phases/20-discovery.md'):
        text = text.replace('a Codex host always seats them on `claude`.',
                            'a Pi host always seats them on the external `claude` CLI.')
        text = replace_once(text,
            'Keep every launch attached and store its returned execution session identifier in the\n'
            'pending-seat handle map. Inspect each terminal result as it arrives and remove only\n'
            'that completed seat from the map. On a cancellation trigger, interrupt only pending\n'
            'sessions. Completed valid siblings remain available for triage, and partial streams\n'
            'remain on disk.',
            'Use the Pi process-ownership procedure in this skill: redirect each launch to\n'
            'session-owned files, retain PID and process start identity per seat/label, and poll\n'
            'terminal artifacts. On cancellation, interrupt only this review\'s pending processes.\n'
            'Completed valid siblings and partial streams remain on disk.')
        text = replace_once(text,
            'Omit `--base` for documents. Use the actual tools available in this Codex\n'
            'session; do not invoke Claude\'s `Agent`, `Monitor`, or `TaskStop` APIs. Keep processes\n'
            'attached to a tool session and wait/poll until all complete.',
            'Omit `--base` for documents. Use Pi\'s actual lowercase tools, never Claude\'s\n'
            '`Agent`, `Monitor`, or `TaskStop` APIs. Poll the session-owned process and\n'
            'terminal artifact map until every launch completes.')
    return text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    expected = {path.relative_to(SOURCE): generate(path.relative_to(SOURCE), path.read_text())
                for path in SOURCE.rglob('*.md')}
    stale = []
    for relative, text in expected.items():
        path = DEST / relative
        if args.check:
            if not path.is_file() or path.read_text() != text:
                stale.append(str(path.relative_to(REPO)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    extra = {path.relative_to(DEST) for path in DEST.rglob('*.md')} - expected.keys()
    if extra:
        stale.extend(str(DEST / path) for path in sorted(extra))
    if stale:
        parser.exit(1, 'Pi workflow drift: ' + ', '.join(stale) + '\n')


if __name__ == '__main__':
    main()
