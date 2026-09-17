#!/bin/bash
# Panel prompt rendering: manifest cost, sibling-site verification text, and render timing.

test_panel_source_snapshot_lists_each_tree_once() {
  python3 - "$SCRIPTS/rev-evidence.py" <<'PY'
import hashlib, importlib.util, sys, tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location('panel_snapshot_cost', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
raw = b''.join(b'line %d\n' % index for index in range(1, 41))
lines = raw.splitlines(True)
oid = hashlib.sha1(b'blob %d\0' % len(raw) + raw).hexdigest()

class Repo:
    listings = 0
    def entries(self, tree):
        Repo.listings += 1
        return {'main.py': ('100644', oid)}
    def blob(self, entry):
        return raw

rows = [{'path': 'main.py', 'blob_tree': '1' * 40, 'blob_mode': '100644', 'blob_oid': oid,
         'line_start': start, 'line_end': start + 1,
         'content_sha256': hashlib.sha256(b''.join(lines[start - 1:start + 1])).hexdigest()}
        for start in range(1, 40, 2)]
manifest = {'source_context': {'snapshot_tree': '1' * 40, 'base_tree': '2' * 40, 'seats': {
    'sol': {'shards': [], 'omitted_source_ranges': rows, 'required_source_ranges': []}}}}
with tempfile.TemporaryDirectory() as session:
    module.validate_source_context_snapshot(Repo(), Path(session), manifest)
assert Repo.listings == 1, Repo.listings
PY
  assert_eq "source snapshot validation lists each tree once, not once per range" "$?" 0
}

panel_prompt_fixture() {  # panel_prompt_fixture <repo> <session> <panel-tsv>
  mkrepo "$1"; mkdir -p "$2"
  printf 'changed\n' > "$1/a.txt"
  printf 'Root rule marker.\n' > "$1/AGENTS.md"
  printf "REV_BASE='%s'\nREV_BRANCH='feature'\nREV_DEFAULT='main'\nREV_ROOT='%s'\nREV_SCOPE='branch'\n" \
    "$(git -C "$1" rev-parse HEAD)" "$1" > "$2/scope.env"
  printf 'a.txt\n' > "$2/files.txt"
  : > "$2/untracked.txt"
  printf '%s\n' '{"seats":[{"seat":"sol","adapter":"codex"},{"seat":"terra","adapter":"codex"},{"seat":"opus","adapter":"claude"},{"seat":"sonnet","adapter":"claude"}]}' > "$2/roster.json"
  printf '%s\t%s\t%s\n' sol correctness-boundaries 'round focus' terra security-state-api 'round focus' \
    opus concurrency-resources-performance 'round focus' \
    sonnet tests-observability-maintenance-regression 'round focus' > "$3"
}

panel_prompt_prepare() {  # panel_prompt_prepare <session> <label> <phase>
  REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$1" "$2" \
    --phase "$3" --assignment sol=correctness-boundaries --assignment terra=security-state-api \
    --assignment opus=concurrency-resources-performance \
    --assignment sonnet=tests-observability-maintenance-regression --full-seat sonnet
}

test_panel_verification_prompts_carry_sibling_site_check() {
  ( local ROOT="$T/panel-sibling-repo" S="$T/panel-sibling-session" TSV="$T/panel-sibling.tsv"
    panel_prompt_fixture "$ROOT" "$S" "$TSV"
    local check='Sibling-site completeness: for each fix commit since the base, name the rule it applies and search the repository for sites, arms, realms, callers and copies (tests, JSDoc, docs) the rule reaches but the commit missed.'
    local prompt seat verification risk

    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1 sol correctness-boundaries 'round focus' --phase verification) || return
    assert_eq "legacy verification prompt appends the sibling-site check to its emphasis" \
      "$(grep -Fxc -- "Round emphasis: round focus $check" "$prompt")" 1
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1 terra security-state-api '' --phase verification) || return
    assert_eq "empty verification emphasis becomes the sibling-site check" \
      "$(grep -Fxc -- "Round emphasis: $check" "$prompt")" 1
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1 opus concurrency-resources-performance verification --phase risk) || return
    assert_eq "legacy risk prompt has no sibling-site check" "$(grep -Fc 'Sibling-site completeness:' "$prompt")" 0
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 1 sonnet tests-observability-maintenance-regression verification) || return
    assert_eq "legacy prompt without a phase has no sibling-site check" \
      "$(grep -Fc 'Sibling-site completeness:' "$prompt")" 0
    assert_exit "unknown prompt phase is rejected" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 1 sol correctness-boundaries 'round focus' --phase review
    "$SCRIPTS/rev-prompt.sh" "$S" 1 --panel "$TSV" --phase verification > "$T/panel-sibling-legacy.out" || return
    while IFS= read -r prompt; do
      assert_eq "legacy verification panel prompt $(basename "$prompt") carries the sibling-site check" \
        "$(grep -Fxc -- "Round emphasis: round focus $check" "$prompt")" 1
    done < "$T/panel-sibling-legacy.out"

    verification=$(panel_prompt_prepare "$S" 2 verification) || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 2 sol correctness-boundaries 'round focus' --evidence "$verification") || return
    assert_eq "evidence verification prompt takes the phase from its manifest" \
      "$(grep -Fxc -- "Round emphasis: round focus $check" "$prompt")" 1
    "$SCRIPTS/rev-prompt.sh" "$S" 2 --panel "$TSV" --evidence "$verification" > "$T/panel-sibling-evidence.out" || return
    assert_eq "evidence verification panel renders four prompts" "$(grep -c . "$T/panel-sibling-evidence.out")" 4
    while IFS= read -r prompt; do
      assert_eq "evidence verification panel prompt $(basename "$prompt") carries the sibling-site check" \
        "$(grep -Fxc -- "Round emphasis: round focus $check" "$prompt")" 1
    done < "$T/panel-sibling-evidence.out"

    risk=$(panel_prompt_prepare "$S" 3 risk) || return
    "$SCRIPTS/rev-prompt.sh" "$S" 3 --panel "$TSV" --evidence "$risk" > "$T/panel-sibling-risk.out" || return
    while IFS= read -r prompt; do
      assert_eq "evidence risk panel prompt $(basename "$prompt") has no sibling-site check" \
        "$(grep -Fc 'Sibling-site completeness:' "$prompt")" 0
    done < "$T/panel-sibling-risk.out"
    printf 'stale\n' > "$S/r3-sol.prompt.md"
    "$SCRIPTS/rev-prompt.sh" "$S" 3 sol correctness-boundaries 'round focus' --phase verification \
      --evidence "$risk" > /dev/null 2> "$T/panel-sibling-conflict.err"
    assert_eq "per-seat --phase that conflicts with the manifest is rejected" "$?" 1
    assert_grep "phase conflict names the manifest phase" "$T/panel-sibling-conflict.err" \
      'evidence manifest phase is risk, not verification'
    assert_exit "phase conflict removes the stale prompt" 1 test -e "$S/r3-sol.prompt.md"

    local repair
    repair=$(REV_PATCH_CHUNKS=auto REV_SOURCE_CONTEXT=1 python3 "$SCRIPTS/rev-evidence.py" prepare "$S" 4x \
      --phase repair --assignment sol=correctness-boundaries --full-seat sol) || return
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 4x sol correctness-boundaries 'round focus' --phase verification \
      --evidence "$repair") || return
    assert_eq "a repair of a verification panel keeps the sibling-site check" \
      "$(grep -Fxc -- "Round emphasis: round focus $check" "$prompt")" 1
    prompt=$("$SCRIPTS/rev-prompt.sh" "$S" 4x sol correctness-boundaries 'round focus' --phase risk \
      --evidence "$repair") || return
    assert_eq "a repair of a risk panel has no sibling-site check" "$(grep -Fc 'Sibling-site completeness:' "$prompt")" 0
    assert_exit "a repair seat cannot claim a plan phase" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 4x sol correctness-boundaries 'round focus' --phase plan --evidence "$repair"
    assert_exit "panel --phase that conflicts with the manifest is rejected" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 3 --panel "$TSV" --phase verification --evidence "$risk"
    for seat in sol terra opus sonnet; do
      assert_exit "panel phase conflict removes the $seat prompt" 1 test -e "$S/r3-$seat.prompt.md"
    done
  )
}

test_panel_render_matches_per_seat_and_validates_manifest_once() {
  ( local ROOT="$T/panel-render-repo" S="$T/panel-render-session" TSV="$T/panel-render.tsv"
    panel_prompt_fixture "$ROOT" "$S" "$TSV"
    local manifest seat lens
    manifest=$(panel_prompt_prepare "$S" 1 risk) || return
    local counter="$T/panel-load-counter"; mkdir -p "$counter"
    cat > "$counter/sitecustomize.py" <<'PY'
import os, sys

LOG = os.environ.get('REV_PANEL_LOAD_LOG')
if LOG:
    def count_manifest_loads(frame, event, arg):
        if (event == 'call' and frame.f_code.co_name == 'validated_manifest'
                and frame.f_code.co_filename.endswith('rev-evidence.py')):
            with open(LOG, 'a') as log:
                log.write('validated_manifest\n')
    sys.setprofile(count_manifest_loads)
PY
    while IFS="$(printf '\t')" read -r seat lens _; do
      : > "$T/panel-load-seat.log"
      PYTHONPATH="$counter" REV_PANEL_LOAD_LOG="$T/panel-load-seat.log" \
        "$SCRIPTS/rev-prompt.sh" "$S" 1 "$seat" "$lens" 'round focus' --evidence "$manifest" > /dev/null || return
      cp "$S/r1-$seat.prompt.md" "$T/panel-render-$seat.expected"
    done < "$TSV"
    assert_eq "per-seat evidence render validates the manifest three times" \
      "$(grep -c . "$T/panel-load-seat.log")" 3

    printf 'stale\n' > "$S/r1-render.json"
    : > "$T/panel-load.log"
    PYTHONPATH="$counter" REV_PANEL_LOAD_LOG="$T/panel-load.log" \
      "$SCRIPTS/rev-prompt.sh" "$S" 1 --panel "$TSV" --evidence "$manifest" > "$T/panel-render.out" || return
    assert_eq "four-seat panel validates the manifest once" "$(grep -c . "$T/panel-load.log")" 1
    assert_eq "panel prints every prompt path in assignment order" "$(cat "$T/panel-render.out")" \
      "$(printf '%s\n' "$S/r1-sol.prompt.md" "$S/r1-terra.prompt.md" "$S/r1-opus.prompt.md" "$S/r1-sonnet.prompt.md")"
    for seat in sol terra opus sonnet; do
      assert_exit "panel $seat prompt is byte-identical to the per-seat render" 0 \
        cmp -s "$T/panel-render-$seat.expected" "$S/r1-$seat.prompt.md"
    done
    python3 - "$S/r1-render.json" <<'PY'
import json, sys
timing = json.load(open(sys.argv[1]))
assert timing['schema_version'] == 1, timing
assert list(timing['seats']) == ['sol', 'terra', 'opus', 'sonnet'], timing
assert all(type(ms) is int and ms >= 0 for ms in timing['seats'].values()), timing
assert type(timing['total_ms']) is int and timing['total_ms'] >= sum(timing['seats'].values()), timing
PY
    assert_eq "panel records per-seat render milliseconds" "$?" 0
    "$SCRIPTS/rev-profile.py" --json "$S" > "$T/panel-render-profile.json" || return
    python3 - "$T/panel-render-profile.json" <<'PY'
import json, sys
panels = json.load(open(sys.argv[1]))['sessions'][0]['render_timing']['panels']
assert [panel['label'] for panel in panels] == ['1'], panels
assert sorted(panels[0]['seats']) == ['opus', 'sol', 'sonnet', 'terra'], panels
PY
    assert_eq "profile reads the panel's recorded render timing" "$?" 0

    local stale
    for stale in sol terra other; do printf 'stale\n' > "$S/r1-$stale.prompt.md"; done
    printf 'newer worktree state\n' > "$ROOT/a.txt"
    "$SCRIPTS/rev-prompt.sh" "$S" 1 --panel "$TSV" --evidence "$manifest" \
      > "$T/panel-render-stale.out" 2> "$T/panel-render-stale.err"
    assert_eq "panel rejects evidence that no longer matches the worktree" "$?" 1
    assert_grep "stale panel names every listed seat" "$T/panel-render-stale.err" \
      'rendered prompts do not match their evidence assignments: sol terra opus sonnet'
    assert_eq "failed panel prints no prompt path" "$(cat "$T/panel-render-stale.out")" ""
    for seat in sol terra opus sonnet; do
      assert_exit "failed panel publishes no $seat prompt" 1 test -e "$S/r1-$seat.prompt.md"
    done
    assert_exit "failed panel removes the stale render timing" 1 test -e "$S/r1-render.json"
    assert_exit "failed panel keeps an unlisted seat's prompt" 0 test -e "$S/r1-other.prompt.md"
    assert_eq "failed panel leaves no temporaries" \
      "$(find "$S" -maxdepth 1 \( -name '.rev-prompt.*' -o -name '.rev-evidence-fragment.*' -o -name '.rev-render.*' \) | wc -l | tr -d ' ')" 0
    printf 'changed\n' > "$ROOT/a.txt"

    local swap real_python shim="$T/panel-swap-shim"
    swap=$(panel_prompt_prepare "$S" 4 risk) || return
    real_python=$(command -v python3); mkdir -p "$shim"
    cat > "$shim/python3" <<'SH'
#!/bin/bash
if [ "${1:-}" = "$REV_SWAP_EVIDENCE" ] && [ "${2:-}" = render-panel ]; then
  "$REV_REAL_PYTHON" "$@" || exit
  printf '\n' >> "$REV_SWAP_MANIFEST"
  exit 0
fi
exec "$REV_REAL_PYTHON" "$@"
SH
    chmod +x "$shim/python3"
    PATH="$shim:$PATH" REV_REAL_PYTHON="$real_python" REV_SWAP_EVIDENCE="$SCRIPTS/rev-evidence.py" \
      REV_SWAP_MANIFEST="$swap" "$SCRIPTS/rev-prompt.sh" "$S" 4 --panel "$TSV" --evidence "$swap" \
      > /dev/null 2> "$T/panel-swap.err"
    assert_eq "manifest change after panel render is rejected" "$?" 1
    assert_grep "manifest change fails the prompt hash binding" "$T/panel-swap.err" \
      'does not bind the evidence manifest exactly once'
    for seat in sol terra opus sonnet; do
      assert_exit "manifest change publishes no $seat prompt" 1 test -e "$S/r4-$seat.prompt.md"
    done

    printf 'sol\tcorrectness-boundaries\tone\nsol\tsecurity-state-api\ttwo\n' > "$T/panel-duplicate.tsv"
    "$SCRIPTS/rev-prompt.sh" "$S" 5 --panel "$T/panel-duplicate.tsv" > /dev/null 2> "$T/panel-duplicate.err"
    assert_eq "panel rejects a duplicate seat" "$?" 1
    assert_grep "duplicate seat is named" "$T/panel-duplicate.err" 'duplicate panel seat: sol'
    printf 'sol\tcorrectness-boundaries\n' > "$T/panel-malformed.tsv"
    assert_exit "panel rejects a line without an emphasis field" 1 \
      "$SCRIPTS/rev-prompt.sh" "$S" 5 --panel "$T/panel-malformed.tsv"
  )
}
