# tests for Task 10 (install-side) — sourced by run-tests.sh
# Covers scripts/lib/set-auto-update.py and install.sh's auto-update step. install.sh is run only
# under REVIEW_COUNCIL_INSTALL_DRY=1, so no real `claude plugin …` call is ever made, and always
# with REVIEW_COUNCIL_SETTINGS pointed at a temp file, so ~/.claude/settings.json is never touched.
SAU="$SCRIPTS/lib/set-auto-update.py"
REPO=$(cd "$SK/../.." && pwd)                      # repo root: install.sh lives beside plugins/
INSTALL="$REPO/install.sh"

jval() {  # jval <file> <dotted.key.path> → the value as compact JSON, exit 1 if absent/unreadable
  python3 - "$1" "$2" <<'PY'
import json, sys
try:
    cur = json.load(open(sys.argv[1], encoding='utf-8'))
except Exception:
    sys.exit(1)
for k in sys.argv[2].split('.'):
    if not isinstance(cur, dict) or k not in cur:
        sys.exit(1)
    cur = cur[k]
print(json.dumps(cur, sort_keys=True, ensure_ascii=False))
PY
}
jothers() {  # jothers <file> → every top-level key except extraKnownMarketplaces, as sorted JSON
  python3 - "$1" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
print(json.dumps({k: v for k, v in d.items() if k != 'extraKnownMarketplaces'}, sort_keys=True))
PY
}
fmode() {  # fmode <path> -> permission bits, e.g. 600
  python3 -c 'import os,sys; print("%03o" % (os.stat(sys.argv[1]).st_mode & 0o777))' "$1"
}
mk_settings() {  # mk_settings <path> — a realistic settings.json with unrelated keys and two marketplaces
  mkdir -p "$(dirname "$1")"
  cat > "$1" <<'JSON'
{
  "model": "opus",
  "permissions": { "allow": ["Bash(ls:*)"], "deny": [] },
  "extraKnownMarketplaces": {
    "review-council": {
      "source": { "source": "github", "repo": "WiktorStarczewski/review-council" }
    },
    "other-market": {
      "autoUpdate": false,
      "source": { "source": "github", "repo": "someone/else" }
    }
  },
  "env": { "FOO": "bar" }
}
JSON
}

test_install_set_auto_update_existing_entry() {
  ( local S="$T/sau-existing/settings.json"; mk_settings "$S"
    python3 "$SAU" "$S" review-council true > "$T/sau.out" 2> "$T/sau.err"; local rc=$?
    assert_eq "exit 0 on a normal settings file" "$rc" 0
    assert_eq "prints the confirmation line" "$(cat "$T/sau.out")" "auto-update on for review-council in $S"
    assert_eq "autoUpdate set to true" "$(jval "$S" extraKnownMarketplaces.review-council.autoUpdate)" "true"
    assert_eq "the entry's existing source object is preserved" \
      "$(jval "$S" extraKnownMarketplaces.review-council.source)" '{"repo": "WiktorStarczewski/review-council", "source": "github"}'
    assert_eq "the other marketplace entry is untouched" \
      "$(jval "$S" extraKnownMarketplaces.other-market)" '{"autoUpdate": false, "source": {"repo": "someone/else", "source": "github"}}'
    assert_eq "every other top-level key is preserved" "$(jothers "$S")" \
      '{"env": {"FOO": "bar"}, "model": "opus", "permissions": {"allow": ["Bash(ls:*)"], "deny": []}}'
    assert_exit "the file is still valid JSON" 0 python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$S"
    assert_exit "ends with a trailing newline" 0 python3 -c 'import sys; sys.exit(0 if open(sys.argv[1],"rb").read().endswith(b"\n") else 1)' "$S"
    assert_grep "written with 2-space indent" "$S" '^  "extraKnownMarketplaces": \{$'
    assert_eq "no .new temp file left behind" "$(ls "$T/sau-existing" | tr '\n' ' ')" "settings.json "
  )
}

test_install_set_auto_update_creates_missing_file() {
  ( local S="$T/sau-missing/settings.json"
    python3 "$SAU" "$S" review-council true > "$T/sau2.out" 2>&1; local rc=$?
    assert_eq "exit 0 when the settings file does not exist" "$rc" 0
    [ -f "$S" ] && ok "creates the settings file" || fail "creates the settings file" "no $S"
    assert_eq "autoUpdate true in the new file" "$(jval "$S" extraKnownMarketplaces.review-council.autoUpdate)" "true"
    # a name with a flag and no repo behind it is not a usable marketplace entry
    assert_eq "the new entry carries the marketplace source too" "$(jval "$S" extraKnownMarketplaces.review-council)" \
      '{"autoUpdate": true, "source": {"repo": "WiktorStarczewski/review-council", "source": "github"}}'
    assert_eq "a file we create is private (settings.json holds secrets)" "$(fmode "$S")" "600"
  )
}

test_install_set_auto_update_unknown_marketplace_invents_no_source() {
  ( local S="$T/sau-unknown/settings.json"
    python3 "$SAU" "$S" someone-elses-market true > /dev/null 2>&1
    assert_eq "an unknown marketplace gets the flag and nothing invented" \
      "$(jval "$S" extraKnownMarketplaces.someone-elses-market)" '{"autoUpdate": true}'
  )
}

test_install_set_auto_update_preserves_file_mode() {  # settings.json can hold secrets: 600 must stay 600
  ( local S="$T/sau-mode/settings.json"; mk_settings "$S"; chmod 600 "$S"
    python3 "$SAU" "$S" review-council true > /dev/null 2>&1
    assert_eq "a 600 settings file is still 600 after the rewrite" "$(fmode "$S")" "600"
    assert_eq "and the edit still landed" "$(jval "$S" extraKnownMarketplaces.review-council.autoUpdate)" "true"
    local S2="$T/sau-mode2/settings.json"; mk_settings "$S2"; chmod 640 "$S2"
    python3 "$SAU" "$S2" review-council true > /dev/null 2>&1
    assert_eq "any other mode is preserved as-is, not reset to the umask default" "$(fmode "$S2")" "640"
  )
}

test_install_set_auto_update_follows_symlinks() {  # dotfile managers symlink settings.json
  ( local D="$T/sau-link"; mkdir -p "$D/store"
    mk_settings "$D/store/real-settings.json"; chmod 600 "$D/store/real-settings.json"
    ln -s "$D/store/real-settings.json" "$D/settings.json"
    python3 "$SAU" "$D/settings.json" review-council true > /dev/null 2>&1; local rc=$?
    assert_eq "exit 0 through a symlink" "$rc" 0
    [ -L "$D/settings.json" ] && ok "the symlink is still a symlink, not a regular file" || fail "the symlink is still a symlink, not a regular file" "replaced"
    assert_eq "the real file behind the link got the flag" \
      "$(jval "$D/store/real-settings.json" extraKnownMarketplaces.review-council.autoUpdate)" "true"
    assert_eq "the real file kept its mode" "$(fmode "$D/store/real-settings.json")" "600"
    assert_eq "no temp file left beside the link" "$(ls "$D" | tr '\n' ' ')" "settings.json store "
  )
}

test_install_set_auto_update_rejects_wrong_shapes() {  # a non-object container must not be silently replaced
  ( local D="$T/sau-shapes"; mkdir -p "$D"
    printf '{ "extraKnownMarketplaces": "nope" }\n' > "$D/a.json"; cp "$D/a.json" "$D/a.before"
    assert_exit "a non-object extraKnownMarketplaces is refused" 1 python3 "$SAU" "$D/a.json" review-council true
    if cmp -s "$D/a.json" "$D/a.before"; then ok "and that file is left byte-identical"; else fail "and that file is left byte-identical" "$(cat "$D/a.json")"; fi
    printf '{ "extraKnownMarketplaces": { "review-council": ["nope"] } }\n' > "$D/b.json"; cp "$D/b.json" "$D/b.before"
    assert_exit "a non-object marketplace entry is refused" 1 python3 "$SAU" "$D/b.json" review-council true
    if cmp -s "$D/b.json" "$D/b.before"; then ok "that file is left byte-identical too"; else fail "that file is left byte-identical too" "$(cat "$D/b.json")"; fi
    printf '["not", "an", "object"]\n' > "$D/c.json"
    assert_exit "a top-level array is still refused" 1 python3 "$SAU" "$D/c.json" review-council true
  )
}

test_install_set_auto_update_empty_file_is_not_corruption() {  # a zero-byte settings.json is absence, not damage
  ( local D="$T/sau-empty"; mkdir -p "$D"
    : > "$D/zero.json"
    python3 "$SAU" "$D/zero.json" review-council true > "$D/out.txt" 2> "$D/err.txt"; local rc=$?
    assert_eq "exit 0 on a zero-byte settings file" "$rc" 0
    assert_eq "says nothing on stderr" "$(cat "$D/err.txt")" ""
    assert_eq "the flag is written" "$(jval "$D/zero.json" extraKnownMarketplaces.review-council.autoUpdate)" "true"
    printf '\n   \n' > "$D/blank.json"
    assert_exit "whitespace-only counts as empty too" 0 python3 "$SAU" "$D/blank.json" review-council true
  )
}

test_install_set_auto_update_false() {
  ( local S="$T/sau-false/settings.json"; mk_settings "$S"
    python3 "$SAU" "$S" review-council false > "$T/sau3.out" 2>&1; local rc=$?
    assert_eq "exit 0 for false" "$rc" 0
    assert_eq "prints 'auto-update off'" "$(cat "$T/sau3.out")" "auto-update off for review-council in $S"
    assert_eq "autoUpdate set to false" "$(jval "$S" extraKnownMarketplaces.review-council.autoUpdate)" "false"
    assert_eq "source still preserved when turning it off" \
      "$(jval "$S" extraKnownMarketplaces.review-council.source)" '{"repo": "WiktorStarczewski/review-council", "source": "github"}'
  )
}

test_install_set_auto_update_bad_json_is_not_destructive() {
  ( local S="$T/sau-bad/settings.json"; mkdir -p "$(dirname "$S")"
    printf '{ this is not json ' > "$S"
    cp "$S" "$T/sau-bad.before"
    python3 "$SAU" "$S" review-council true > "$T/sau4.out" 2> "$T/sau4.err"; local rc=$?
    assert_eq "exit 1 on unreadable JSON" "$rc" 1
    assert_eq "one line of explanation" "$(wc -l < "$T/sau4.err" | tr -d ' ')" "1"
    assert_grep "the message names the file" "$T/sau4.err" "$(basename "$S")"
    if cmp -s "$S" "$T/sau-bad.before"; then ok "the unreadable file is left byte-identical"; else fail "the unreadable file is left byte-identical" "$(cat "$S")"; fi
    assert_eq "no .new temp file left behind" "$(ls "$T/sau-bad" | tr '\n' ' ')" "settings.json "
  )
}

test_install_set_auto_update_usage() {
  ( assert_exit "wrong argument count is a usage error" 2 python3 "$SAU" "$T/nope.json" review-council
    assert_exit "a non-boolean third argument is a usage error" 2 python3 "$SAU" "$T/nope.json" review-council yes
    [ -f "$T/nope.json" ] && fail "a usage error writes nothing" "created $T/nope.json" || ok "a usage error writes nothing"
  )
}

test_install_dry_run_enables_auto_update() {
  ( local S="$T/inst-dry/settings.json"
    REVIEW_COUNCIL_INSTALL_DRY=1 REVIEW_COUNCIL_SETTINGS="$S" bash "$INSTALL" > "$T/inst.out" 2>&1; local rc=$?
    assert_eq "install.sh exits 0 in dry mode" "$rc" 0
    assert_grep "prints the marketplace command it would run" "$T/inst.out" 'claude plugin marketplace add WiktorStarczewski/review-council'
    assert_grep "prints the install command it would run" "$T/inst.out" 'claude plugin install review-council@review-council'
    assert_grep "says auto-update is on" "$T/inst.out" '^Auto-update is on for the review-council marketplace'
    assert_grep "says how to turn it off" "$T/inst.out" 'rerun this installer with --no-auto-update'
    assert_eq "autoUpdate written to the settings file" "$(jval "$S" extraKnownMarketplaces.review-council.autoUpdate)" "true"
  )
}

test_install_dry_run_no_auto_update_flag() {
  ( local S="$T/inst-noauto/settings.json"; mk_settings "$S"; cp "$S" "$T/inst-noauto.before"
    REVIEW_COUNCIL_INSTALL_DRY=1 REVIEW_COUNCIL_SETTINGS="$S" bash "$INSTALL" --no-auto-update > "$T/inst2.out" 2>&1; local rc=$?
    assert_eq "install.sh exits 0 with --no-auto-update" "$rc" 0
    assert_grep "still prints the install command" "$T/inst2.out" 'claude plugin install review-council@review-council'
    if cmp -s "$S" "$T/inst-noauto.before"; then ok "settings.json is left untouched"; else fail "settings.json is left untouched" "$(cat "$S")"; fi
    assert_grep "the message says auto-update was not enabled" "$T/inst2.out" '^Auto-update is off'
  )
}

test_install_dry_run_no_auto_update_env() {
  ( local S="$T/inst-noauto-env/settings.json"
    REVIEW_COUNCIL_INSTALL_DRY=1 REVIEW_COUNCIL_NO_AUTO_UPDATE=1 REVIEW_COUNCIL_SETTINGS="$S" \
      bash "$INSTALL" > "$T/inst3.out" 2>&1; local rc=$?
    assert_eq "install.sh exits 0 with REVIEW_COUNCIL_NO_AUTO_UPDATE=1" "$rc" 0
    [ -f "$S" ] && fail "the env opt-out writes no settings file" "created $S" || ok "the env opt-out writes no settings file"
  )
}

test_install_inline_json_edit_matches_lib() {  # install.sh runs via curl before the plugin exists, so it
  # carries its own copy of the JSON-editing code; the two copies must not drift.
  ( sed -n '/^# --- begin json-edit/,/^# --- end json-edit/p' "$SAU"     > "$T/jsonedit-lib.txt"
    sed -n '/^# --- begin json-edit/,/^# --- end json-edit/p' "$INSTALL" > "$T/jsonedit-inst.txt"
    [ -s "$T/jsonedit-lib.txt" ]  && ok "set-auto-update.py has the json-edit markers"  || fail "set-auto-update.py has the json-edit markers" "block empty"
    [ -s "$T/jsonedit-inst.txt" ] && ok "install.sh has the json-edit markers"          || fail "install.sh has the json-edit markers" "block empty"
    if diff -u "$T/jsonedit-lib.txt" "$T/jsonedit-inst.txt" > "$T/jsonedit.diff" 2>&1
      then ok "the two json-edit blocks are byte-identical"
      else fail "the two json-edit blocks are byte-identical" "$(head -20 "$T/jsonedit.diff")"; fi
  )
}

test_install_manifest_single_source_version() {  # the plugin's version lives in exactly one file
  ( local MP="$REPO/.claude-plugin/marketplace.json" PJ="$SK/.claude-plugin/plugin.json"
    local entry_version; entry_version=$(python3 - "$MP" <<'PY'
import json, sys
d = json.load(open(sys.argv[1], encoding='utf-8'))
p = [p for p in d.get('plugins', []) if p.get('name') == 'review-council']
print('missing-entry' if not p else p[0].get('version', ''))
PY
)
    assert_eq "the marketplace entry pins no version (the manifest silently wins over it)" "$entry_version" ""
    local pv; pv=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["version"])' "$PJ")
    assert_grep "plugin.json carries a dotted-integer version" "$PJ" '"version": "[0-9]+(\.[0-9]+)+"'
    assert_eq "plugin.json is at the version this task ships" "$pv" "0.1.1"
    assert_grep "CHANGELOG has a section for it" "$REPO/CHANGELOG.md" "^## $(echo "$pv" | sed 's/\./\\./g')\$"
  )
}

test_install_dry_run_reports_a_failed_edit_distinctly() {  # a failed write is not the same as opting out
  ( local D="$T/inst-failed"; mkdir -p "$D/settings.json"   # a directory where the file should be: the edit must fail
    REVIEW_COUNCIL_INSTALL_DRY=1 REVIEW_COUNCIL_SETTINGS="$D/settings.json" bash "$INSTALL" > "$T/inst4.out" 2>&1; local rc=$?
    assert_eq "the install itself still succeeds" "$rc" 0
    assert_grep "the failure is reported in its own words" "$T/inst4.out" '^Auto-update could NOT be enabled'
    assert_grep "and it names the file" "$T/inst4.out" "$(basename "$D/settings.json")"
    assert_nogrep "not the opted-out wording, which would be a lie" "$T/inst4.out" 'rerun this installer without --no-auto-update'
  )
}

test_install_readme_documents_the_settings_write() {  # the one file the installer touches outside Claude Code's install
  ( assert_grep "README says the file is rewritten at 2-space indent" "$REPO/README.md" '2-space indent'
    assert_grep "README says every other setting is preserved" "$REPO/README.md" 'every other setting preserved'
  )
}
