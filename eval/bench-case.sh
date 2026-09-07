#!/bin/bash
# bench-case.sh <name> <clone-url> <review-head-sha> <base-sha> <out-dir> [lens]
# Blind held-out run of one PR at its review-time head: isolated checkout (head + ancestors only, no remote), preflight
# with the given base, one prompt per roster seat with the lens (default: simplicity) and REV_SEAT_OFFLINE=1, the CLI
# seats through rev-seat.sh and the Claude seat through `claude -p`, all in parallel. Writes <out-dir>/r1-<seat>.json.
# Prints one line per seat (exit code, finding count) and nothing about the content.
set -u
NAME=$1; URL=$2; HEAD_SHA=$3; BASE_SHA=$4; OUT=$5; LENS=${6:-simplicity}
HERE=$(cd "$(dirname "$0")" && pwd); SCRIPTS="$HERE/../plugins/review-council/scripts"
EMPH="Simplicity first, then correctness, edge cases, error handling"
mkdir -p "$OUT"; OUT=$(cd "$OUT" && pwd); REPO="$OUT/repo"   # absolute: preflight resolves --write against its own cwd
if [ ! -d "$REPO/.git" ]; then
  git init -q "$REPO" && git -C "$REPO" remote add origin "$URL" && git -C "$REPO" fetch -q origin "$HEAD_SHA" \
    && git -C "$REPO" checkout -q --detach "$HEAD_SHA" && git -C "$REPO" branch -q main "$BASE_SHA" && git -C "$REPO" remote remove origin \
    || { echo "$NAME: checkout failed"; exit 1; }
  [ "$(git -C "$REPO" rev-list --all --not HEAD | wc -l | tr -d ' ')" = 0 ] || { echo "$NAME: history after HEAD present"; exit 1; }
fi
S="$OUT/session"; mkdir -p "$S"
( cd "$REPO" && "$SCRIPTS/rev-preflight.sh" --scope branch --base "$BASE_SHA" --write "$S" ) > "$OUT/preflight.txt" 2>&1 || { echo "$NAME: preflight failed: $(tail -1 "$OUT/preflight.txt")"; exit 1; }
SEATS=$(python3 -c "import json,sys; print(' '.join(s['seat'] for s in json.load(open(sys.argv[1]))['seats'] if not s.get('extra')))" "$S/roster.json")
for seat in $SEATS; do REV_SEAT_OFFLINE=1 "$SCRIPTS/rev-prompt.sh" "$S" 1 "$seat" "$LENS" "$EMPH" >/dev/null || { echo "$NAME: render failed for $seat"; exit 1; }; done
pids=(); [ -n "$SEATS" ] || { echo "$NAME: no seats in roster"; exit 1; }
for seat in $SEATS; do
  adapter=$(python3 -c "import json,sys; print(next(s['adapter'] for s in json.load(open(sys.argv[1]))['seats'] if s['seat']==sys.argv[2]))" "$S/roster.json" "$seat")
  if [ "$adapter" = agent ]; then
    ( cd "$REPO" && claude -p "Your instructions are in $S/r1-$seat.prompt.md. Read that file first with the Read tool, follow it exactly, and return ONLY the JSON object it asks for. You are one seat inside a review that is already running: never invoke /review-council:rev, /review-council:stack, or claude -p, and never start a review by any other means. This review is read-only and offline: do not create, edit or delete any file, do not run any git command that changes state, do not fetch or use the network, and do not use any other checkout of this repository on this machine. The repository is at $REPO. Reason at maximum depth; there is no time or token budget." \
        --model opus --permission-mode bypassPermissions --effort max --max-turns 150 --output-format text </dev/null > "$S/r1-$seat.raw" 2> "$S/r1-$seat.log"
      python3 - "$S/r1-$seat.raw" "$S/r1-$seat.json" <<'PY'
import sys, json, html
t=open(sys.argv[1], errors='replace').read(); s=t[t.find('{'):t.rfind('}')+1]
try: obj=json.loads(s)
except Exception:
    try: obj=json.loads(html.unescape(s))
    except Exception: sys.exit(2)
obj.pop('$schema',None)
for f in obj.get('findings',[]): f.pop('evidence_note',None)
open(sys.argv[2],'w').write(json.dumps(obj,indent=1,ensure_ascii=False))
PY
      rc=$?; [ "$rc" = 0 ] && python3 "$SCRIPTS/lib/validate-findings.py" "$S/r1-$seat.json" >/dev/null 2>&1 || rc=2; echo "$rc" > "$S/r1-$seat.exit" ) &
  else
    ( "$SCRIPTS/rev-seat.sh" "$seat" "$S" 1 "$S/r1-$seat.prompt.md" > "$S/r1-$seat.seat.out" 2>&1 ) &
  fi
  pids+=($!)
done
wait "${pids[@]}"
for seat in $SEATS; do
  n=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['findings']))" "$S/r1-$seat.json" 2>/dev/null || echo "?")
  echo "$NAME seat=$seat exit=$(cat "$S/r1-$seat.exit" 2>/dev/null || echo ?) findings=$n"
done
