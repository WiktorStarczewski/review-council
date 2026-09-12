#!/bin/bash
# bench-case.sh <name> <clone-url> <review-head-sha> <base-sha> <out-dir> [lenses] [owner/repo pr]
# Blind held-out run of one PR at its review-time head: isolated checkout (head + ancestors only, no remote), preflight
# with the given base, one prompt per roster seat with the lens (default: simplicity) and REV_SEAT_OFFLINE=1, the CLI
# seats through rev-seat.sh and the Claude seat through `claude -p`, all in parallel. Writes <out-dir>/r1-<seat>.json.
# Prints one line per seat (exit code, finding count) and nothing about the content.
set -u
NAME=$1; URL=$2; HEAD_SHA=$3; BASE_SHA=$4; OUT=$5; LENSES=${6:-simplicity}   # comma list, dealt like the skill: seat i gets lenses[(i+1) mod L]
PR_REPO=${7:-}; PR_NUM=${8:-}   # when given, the PR title+body is fetched with gh and passed to every prompt (--pr)
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
( cd "$REPO" && "$SCRIPTS/rev-preflight.sh" --scope branch --base "$BASE_SHA" --write "$S" ) > "$OUT/preflight.txt" 2>&1
preflight_rc=$?
if [ "$preflight_rc" -ne 0 ]; then
  echo "$NAME: preflight failed: $(tail -1 "$OUT/preflight.txt")"
  exit "$preflight_rc"
fi
SEATS=$(python3 -c "import json,sys; print(' '.join(s['seat'] for s in json.load(open(sys.argv[1]))['seats'] if not s.get('extra')))" "$S/roster.json")
# Filtered dependency view: every registry crate pinned in the checkout's Cargo.lock, minus any crate this repository
# itself publishes (any [package] name under the checkout), linked from the real registry into $S/deps. Seats are told
# this is the only dependency source; a whole-registry grep would otherwise return later versions of the repo's own crates.
DEPS="$S/deps"; rm -rf "$DEPS"; mkdir -p "$DEPS"
python3 - "$REPO" "$DEPS" <<'PY2'
import re, sys, pathlib, os, glob
repo, deps = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
own = set()
for t in repo.rglob('Cargo.toml'):
    if 'target' in t.parts: continue
    m = re.search(r'^\[package\][^\[]*?^name\s*=\s*"([^"]+)"', t.read_text(errors='replace'), re.M | re.S)
    if m: own.add(m.group(1))
lock = repo / 'Cargo.lock'
if not lock.exists(): sys.exit(0)
pins = set(re.findall(r'^name = "([^"]+)"\nversion = "([^"]+)"\nsource = "registry', lock.read_text(errors='replace'), re.M))
srcs = glob.glob(os.path.expanduser('~/.cargo/registry/src/*/'))
n = 0
for name, ver in pins:
    if name in own: continue
    for s in srcs:
        d = pathlib.Path(s) / f"{name}-{ver}"
        if d.is_dir():
            (deps / f"{name}-{ver}").symlink_to(d); n += 1; break
print(f"deps view: {n} crates linked, {len(own)} own crate names excluded")
PY2
deps_rc=$?
if [ "$deps_rc" -ne 0 ]; then
  echo "$NAME: dependency view failed"
  exit "$deps_rc"
fi
export REV_DEPS_DIR="$DEPS"
PRARGS=(); if [ -n "$PR_REPO" ] && [ -n "$PR_NUM" ]; then gh pr view "$PR_NUM" --repo "$PR_REPO" --json title,body --jq '"# " + .title + "\n\n" + .body' > "$S/pr.md" 2>/dev/null && [ -s "$S/pr.md" ] && PRARGS=(--pr "$S/pr.md"); fi
i=0; for seat in $SEATS; do lens=$(python3 -c "import sys; L=sys.argv[1].split(','); print(L[(int(sys.argv[2])+1) % len(L)])" "$LENSES" "$i"); REV_SEAT_OFFLINE=1 "$SCRIPTS/rev-prompt.sh" "$S" 1 "$seat" "$lens" "$EMPH" ${PRARGS[@]+"${PRARGS[@]}"} >/dev/null || { echo "$NAME: render failed for $seat"; exit 1; }; echo "$seat $lens" >> "$S/lenses.txt"; i=$((i+1)); done
pids=(); [ -n "$SEATS" ] || { echo "$NAME: no seats in roster"; exit 1; }
for seat in $SEATS; do
  adapter=$(python3 -c "import json,sys; print(next(s['adapter'] for s in json.load(open(sys.argv[1]))['seats'] if s['seat']==sys.argv[2]))" "$S/roster.json" "$seat")
  if [ "$adapter" = agent ]; then
    ( cd "$REPO" && claude -p "Your instructions are in $S/r1-$seat.prompt.md. Read that file first with the Read tool, follow it exactly, and return ONLY the JSON object it asks for. You are one seat inside a review that is already running: never invoke /review-council:rev, /review-council:stack, or claude -p, and never start a review by any other means. This review is read-only and offline: do not create, edit or delete any file, do not run any git command that changes state, do not fetch or use the network, and do not use any other checkout of this repository on this machine. The repository is at $REPO. Complete every assigned check and substantiate each finding from the assigned source." \
        --model opus --permission-mode bypassPermissions --effort max --max-turns 150 --output-format text </dev/null > "$S/r1-$seat.raw" 2> "$S/r1-$seat.log"
      agent_rc=$?
      rc=$agent_rc
      if [ "$agent_rc" -eq 0 ]; then
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
        rc=$?
        [ "$rc" -eq 0 ] && python3 "$SCRIPTS/lib/validate-findings.py" "$S/r1-$seat.json" >/dev/null 2>&1 || rc=2
      fi
      echo "$rc" > "$S/r1-$seat.exit"; exit "$rc" ) &
  else
    ( "$SCRIPTS/rev-seat.sh" "$seat" "$S" 1 "$S/r1-$seat.prompt.md" > "$S/r1-$seat.seat.out" 2>&1 ) &
  fi
  pids+=($!)
done
for pid in "${pids[@]}"; do wait "$pid" || :; done
failed=0
for seat in $SEATS; do
  n=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['findings']))" "$S/r1-$seat.json" 2>/dev/null || echo "?")
  seat_rc=$(cat "$S/r1-$seat.exit" 2>/dev/null || echo ?)
  echo "$NAME seat=$seat exit=$seat_rc findings=$n"
  [ "$seat_rc" = 0 ] || failed=1
done
exit "$failed"
