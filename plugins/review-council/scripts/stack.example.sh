# Copy this file, edit it, then:   "${CLAUDE_PLUGIN_ROOT}/scripts/stack.sh" my-stack.sh
#
# Legs in DEPENDENCY ORDER: review what the others build on first — its findings change what the dependents
# should say. Give every leg a PREMISE: what the PR claims, what is already known, and the claim you most want
# attacked. A leg with no premise "fixes" things that are not broken.
#
#   run_leg <repo-path> <rounds> <label> "<premise>"
#   rounds: 3 for a large or never-reviewed PR, 1-2 for a small or already-reviewed one.
legs() {
  run_leg "$HOME/src/protocol" 3 protocol "Guarded multisig pays fees via fee::pay_fee. ATTACK: the claim that no output note exists before auth runs."
  run_leg "$HOME/src/sdk"      2 sdk      "Consumes protocol#NNNN through a linked-PR marker. Focus on the newest commit only."
  run_leg "$HOME/src/app"      3 app      "~50 commits adding X plus its E2E harness. NEVER REVIEWED."
}
SEAM_REPO="$HOME/src/app"     # phase 2 runs here — pick the repo with the widest surface
CRITIC_REPO="$HOME/src/app"   # phase 3 runs here
# Knobs (defaults shown): PASSES=2 STALL_SECS=1800 STATUS_EVERY=600 MAX_ATTEMPTS=4 NO_PUSH=0
