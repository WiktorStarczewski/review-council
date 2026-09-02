#!/bin/bash
# Portability helpers: source this file. macOS ships BSD stat/date; Linux ships GNU. Nothing else differs for us.
rc_mtime() {  # rc_mtime <path> → epoch seconds, empty if missing
  # GNU first: on GNU coreutils `stat -f` means --file-system and would SUCCEED with a wrong number; BSD stat
  # rejects -c, so the fallback order below is the only one that is correct on both.
  stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null
}
rc_touch_ago() {  # rc_touch_ago <seconds> <path> → set <path>'s mtime to now-<seconds> (creates it)
  local ts
  ts=$(date -v-"$1"S +%Y%m%d%H%M.%S 2>/dev/null || date -d "-$1 seconds" +%Y%m%d%H%M.%S 2>/dev/null) || return 1
  touch -t "$ts" "$2"
}
rc_newest_mtime() {  # rc_newest_mtime <dir> → newest file mtime under <dir>, empty if none
  local f best=""
  while IFS= read -r f; do
    local m; m=$(rc_mtime "$f"); [ -n "$m" ] && { [ -z "$best" ] || [ "$m" -gt "$best" ]; } && best=$m
  done < <(find "$1" -type f 2>/dev/null)
  printf '%s' "$best"
}
