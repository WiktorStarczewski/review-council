import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const skill = fileURLToPath(new URL('../plugins/review-council/pi-skills/review-council-rev/SKILL.md', import.meta.url));
const help = `Review Council for Pi
/rev [branch|uncommitted|path|PR URL] [rounds] [--read-only] [--base ref]
/rev --setup   Check local prerequisites without provider calls
/rev --help    Show this help
Provider reviewers use separately authenticated CLIs. Pi stack hosting is not supported.`;

export default function reviewCouncil(pi) {
  pi.registerCommand('rev', {
    description: 'Review Council: independent multi-model review and fixes',
    handler: async (args, ctx) => {
      if (args.trim() === '--help') {
        ctx.ui.notify(help, 'info');
        return;
      }
      if (args.trim() === '--setup') {
        const result = await pi.exec('bash', ['-c',
          'for tool in bash git python3 gh rg codex claude gemini; do ' +
          'if command -v "$tool" >/dev/null 2>&1; then printf "OK %s\\n" "$tool"; ' +
          'else printf "MISSING %s\\n" "$tool"; fi; done'],
        { cwd: ctx.cwd, timeout: 10000, maxBuffer: 8192 });
        ctx.ui.notify(`${result.stdout}\n${result.code === 0 ? '' : 'Prerequisite check failed.\n'}` +
          'Required: bash, git, python3, rg; gh for PR scopes/publication.\n' +
          'Reviewers: codex login; claude auth login; optionally Gemini sign-in.\n' +
          'Pi login does not authenticate these CLIs. This checks presence only; ' +
          'preflight checks actual availability and consumes provider usage.',
        result.code === 0 ? 'info' : 'error');
        return;
      }
      if (process.env.REV_ACTIVE) {
        ctx.ui.notify('Review Council is already active; nested reviews are refused.', 'error');
        return;
      }
      if (!ctx.isIdle()) {
        ctx.ui.notify('Wait until Pi is idle before starting /rev.', 'warning');
        return;
      }
      // Bind the installed skill directly so another host's shared rev cannot shadow it.
      const text = await readFile(skill, 'utf8');
      pi.sendUserMessage(`Follow the Review Council Pi skill at ${skill}.\n` +
        `Use REVIEW_COUNCIL_HOST=pi on every runner invocation.\n\n${text}\n\nUser review request:\n${args}`);
    },
  });
}
