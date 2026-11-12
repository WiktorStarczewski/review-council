import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';

const skill = fileURLToPath(new URL('../plugins/review-council/pi-skills/review-council-rev/SKILL.md', import.meta.url));
const help = `Review Council for Pi
/council [branch|uncommitted|path|PR URL] [rounds] [--read-only] [--base ref]
/council eco|high   Set the session panel without starting a review
/council status     Show the session panel
/council --setup    Check local prerequisites without provider calls
/council --help     Show this help
/rev               Compatibility alias for /council
Provider reviewers use separately authenticated CLIs. Pi stack hosting is not supported.`;

export default function reviewCouncil(pi) {
  let mode = 'eco';

  const policy = () => `Review Council session default: ${mode.toUpperCase()}.\n` +
    `For every NEW Council review, including conversational and direct-skill requests, follow ${skill}.\n` +
    `When calling rev-panel-request.py, prepend "mode: ${mode === 'high' ? 'high' : 'normal'}\\n" to the review request text.\n` +
    'ECO uses four Luna seats; HIGH uses Opus, Sol, Sonnet and Luna under the installed preset rules.\n' +
    'An explicit per-review mode or roster overrides this default without changing the session setting.\n' +
    'Reuse an initialized review\'s frozen roster; never rebuild it because the session mode changed.\n' +
    'This setting does not itself request or authorize a review.';

  const syncStatus = (ctx) => {
    if (!ctx.hasUI) return;
    const fg = (color, text) => ctx.ui.theme?.fg(color, text) ?? text;
    ctx.ui.setStatus('review-council', '⚖️ ' + fg('muted', 'council: ') +
      fg('text', mode === 'high' ? '🔥 HIGH' : '🌿 ECO'));
  };

  const restore = (_event, ctx) => {
    mode = 'eco';
    for (const entry of ctx.sessionManager.getBranch()) {
      if (entry.type === 'custom' && entry.customType === 'review-council-mode' &&
          ['eco', 'high'].includes(entry.data?.mode)) mode = entry.data.mode;
    }
    syncStatus(ctx);
  };
  pi.on('session_start', restore);
  pi.on('session_tree', restore);
  pi.on('before_agent_start', (event) => {
    if (event.systemPromptOptions?.sections) {
      event.systemPromptOptions.sections.review_council = policy();
      return;
    }
    return { systemPrompt: `${event.systemPrompt || ''}\n\n${policy()}` };
  });

  const command = {
    description: 'Review Council: review scope, eco, high, status, --help, --setup',
    getArgumentCompletions: (prefix) => {
      const values = ['eco', 'high', 'status', '--help', '--setup']
        .filter(value => value.startsWith(prefix.trimStart().toLowerCase()));
      return values.length ? values.map(value => ({ value, label: value })) : null;
    },
    handler: async (args, ctx) => {
      const subcommand = args.trim().toLowerCase();
      if (subcommand === 'eco' || subcommand === 'high') {
        pi.appendEntry('review-council-mode', { mode: subcommand });
        mode = subcommand;
        syncStatus(ctx);
        ctx.ui?.notify(`Council session mode set to ${mode.toUpperCase()}. Applies to new reviews.`, 'info');
        return;
      }
      if (subcommand === 'status') {
        ctx.ui?.notify(`Council session mode: ${mode.toUpperCase()}.`, 'info');
        return;
      }
      if (subcommand === '--help') {
        ctx.ui.notify(help, 'info');
        return;
      }
      if (subcommand === '--setup') {
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
        ctx.ui.notify('Wait until Pi is idle before starting /council.', 'warning');
        return;
      }
      // Bind the installed skill directly so another host's shared rev cannot shadow it.
      const text = await readFile(skill, 'utf8');
      pi.sendUserMessage(`Follow the Review Council Pi skill at ${skill}.\n` +
        `Use REVIEW_COUNCIL_HOST=pi on every runner invocation.\n\n${text}\n\n${policy()}\n\nUser review request:\n${args}`);
    },
  };
  pi.registerCommand('council', command);
  pi.registerCommand('rev', command);
}
