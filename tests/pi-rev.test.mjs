import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const extensionURL = new URL('../pi/rev.ts', import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));

async function harness({ idle = true, entries = [], hasUI = true } = {}) {
  assert.ok(existsSync(extensionURL), 'native /rev extension must exist');
  const { default: extension } = await import(extensionURL);
  const commands = new Map();
  const messages = [];
  const notices = [];
  const executions = [];
  const events = new Map();
  const statuses = new Map();
  const saved = [];
  const pi = {
    on: (name, handler) => events.set(name, handler),
    appendEntry: (customType, data) => {
      const entry = { type: 'custom', customType, data };
      saved.push(entry);
      entries.push(entry);
    },
    registerCommand: (name, command) => commands.set(name, command),
    sendUserMessage: (message, options) => messages.push({ message, options }),
    exec: async (command, args, options) => {
      executions.push({ command, args, options });
      return { code: 0, stdout: '/usr/bin/tool\n', stderr: '', killed: false, truncated: false };
    },
  };
  extension(pi);
  const ctx = {
    isIdle: () => idle,
    hasUI,
    cwd: '/tmp/reviewed project',
    sessionManager: { getBranch: () => entries },
    ui: {
      notify: (...args) => notices.push(args),
      setStatus: (key, text) => statuses.set(key, text),
      theme: { fg: (_color, text) => text },
    },
  };
  const emit = (name, event = {}) => events.get(name)?.(event, ctx);
  await emit('session_start', { reason: 'startup' });
  return { commands, messages, notices, executions, ctx, statuses, saved, entries, emit,
    invoke: (args = '', name = 'council') => commands.get(name)?.handler(args, ctx) };
}

test('registers /council and /rev and binds the installed Pi workflow without shell interpretation', async () => {
  const h = await harness();
  assert.deepEqual([...h.commands.keys()], ['council', 'rev']);
  const args = 'https://github.com/o/r/pull/12 --read-only "x y" $(touch /tmp/never)';
  await h.invoke(args);
  assert.equal(h.messages.length, 1);
  assert.ok(h.messages[0].message.includes(root + 'plugins/review-council/pi-skills/review-council-rev/SKILL.md'));
  assert.ok(h.messages[0].message.endsWith(args));
  assert.ok(h.messages[0].message.includes('REVIEW_COUNCIL_HOST=pi'));
  assert.equal(h.executions.length, 0);
});

test('bare council starts a review and rev remains an equivalent alias', async () => {
  const h = await harness();
  await h.invoke();
  await h.invoke('', 'rev');
  assert.equal(h.messages.length, 2);
  assert.equal(h.messages[0].message, h.messages[1].message);
  assert.match(h.messages[0].message, /mode: normal/);
});

test('Council owns its footer without any Ponytail integration', async () => {
  const h = await harness();
  assert.deepEqual([...h.statuses], [['review-council', '⚖️ council: 🌿 ECO']]);
});

for (const mode of ['eco', 'high']) {
  test(`${mode} selection persists and updates the independent footer without a review`, async () => {
    const h = await harness();
    await h.invoke(` ${mode.toUpperCase()} `);
    assert.deepEqual(h.saved, [{ type: 'custom', customType: 'review-council-mode', data: { mode } }]);
    assert.equal(h.statuses.get('review-council'), mode === 'eco' ? '⚖️ council: 🌿 ECO' : '⚖️ council: 🔥 HIGH');
    assert.equal(h.messages.length, 0);
    assert.equal(h.executions.length, 0);
    await h.invoke('status');
    assert.match(h.notices.at(-1)[0], new RegExp(mode, 'i'));
    assert.equal(h.saved.length, 1);
    assert.equal(h.messages.length, 0);
  });
}

test('autocomplete offers complete mode commands and filters the prefix', async () => {
  const h = await harness();
  const complete = h.commands.get('council')?.getArgumentCompletions;
  assert.equal(typeof complete, 'function');
  assert.deepEqual(complete('h'), [{ value: 'high', label: 'high' }]);
  assert.ok(complete('').some(item => item.value === 'eco'));
  assert.equal(complete('branch '), null);
});

for (const reason of ['startup', 'reload', 'resume', 'fork']) {
  test(`${reason} restores the selected mode from the active branch`, async () => {
    const h = await harness({ entries: [
      { type: 'custom', customType: 'review-council-mode', data: { mode: 'high' } },
      { type: 'custom', customType: 'review-council-mode', data: { mode: 'invalid' } },
      { type: 'custom', customType: 'ponytail-mode', data: { mode: 'eco' } },
    ] });
    await h.emit('session_start', { reason });
    assert.equal(h.statuses.get('review-council'), '⚖️ council: 🔥 HIGH');
    assert.equal(h.saved.length, 0);
  });
}

test('tree navigation and new sessions do not retain a previous mode', async () => {
  const h = await harness();
  await h.invoke('high');
  h.entries.length = 0;
  await h.emit('session_tree');
  assert.equal(h.statuses.get('review-council'), '⚖️ council: 🌿 ECO');
  await h.invoke('high');
  h.entries.length = 0;
  await h.emit('session_start', { reason: 'new' });
  assert.equal(h.statuses.get('review-council'), '⚖️ council: 🌿 ECO');
});

test('headless session keeps mode policy without trying to render status', async () => {
  const h = await harness({ hasUI: false });
  h.ctx.ui = undefined;
  await h.invoke('high');
  await h.emit('session_start');
  const event = { systemPromptOptions: { sections: {} } };
  await h.emit('before_agent_start', event);
  assert.match(event.systemPromptOptions.sections.review_council, /mode: high/);
});

test('mode policy covers conversational reviews and defers to explicit and frozen rosters', async () => {
  const h = await harness();
  await h.invoke('high');
  const event = { systemPrompt: 'base', systemPromptOptions: { sections: { other: 'unchanged' } } };
  assert.equal(await h.emit('before_agent_start', event), undefined);
  assert.equal(event.systemPromptOptions.sections.other, 'unchanged');
  const policy = event.systemPromptOptions.sections.review_council;
  assert.match(policy, /HIGH uses two Sol seats and two Opus seats/);
  assert.match(policy, /mode: high/);
  assert.match(policy, /explicit.*override/i);
  assert.match(policy, /frozen roster/i);
  assert.ok(policy.includes('review-council-rev/SKILL.md'));
  await h.invoke('branch high effort 4*luna');
  assert.match(h.messages[0].message, /mode: high/);
  assert.ok(h.messages[0].message.endsWith('branch high effort 4*luna'));
  assert.equal(h.saved.length, 1);
});

test('older Pi prompt fallback preserves existing instructions and mode', async () => {
  const h = await harness();
  const result = await h.emit('before_agent_start', { systemPrompt: 'existing instructions' });
  assert.ok(result.systemPrompt.startsWith('existing instructions\n\n'));
  assert.match(result.systemPrompt, /mode: normal/);
});

test('only exact subcommands change mode; scope paths pass through unchanged', async () => {
  const h = await harness();
  await h.invoke('./high --read-only');
  assert.equal(h.saved.length, 0);
  assert.ok(h.messages[0].message.endsWith('./high --read-only'));
});

test('busy invocation refuses rather than queues a second review', async () => {
  const h = await harness({ idle: false });
  await h.invoke('branch');
  assert.equal(h.messages.length, 0);
  assert.match(h.notices[0][0], /idle|busy/i);
});

test('nested invocation refuses before starting review', async () => {
  const h = await harness();
  const previous = process.env.REV_ACTIVE;
  process.env.REV_ACTIVE = '1';
  try { await h.invoke('branch'); }
  finally {
    if (previous === undefined) delete process.env.REV_ACTIVE;
    else process.env.REV_ACTIVE = previous;
  }
  assert.equal(h.messages.length, 0);
  assert.match(h.notices[0][0], /nested|active/i);
});

test('help never starts a model or provider call', async () => {
  const h = await harness();
  await h.invoke('--help');
  assert.equal(h.messages.length, 0);
  assert.equal(h.executions.length, 0);
  assert.match(h.notices[0][0], /--setup/);
});

test('setup checks tools with bounded execution but never calls provider models', async () => {
  const h = await harness();
  await h.invoke('--setup');
  assert.equal(h.messages.length, 0);
  assert.equal(h.executions.length, 1);
  assert.equal(h.executions[0].command, 'bash');
  assert.ok(h.executions[0].args[1].includes('command -v'));
  assert.ok(h.executions[0].options.timeout <= 10000);
  assert.match(h.notices[0][0], /codex login/);
});

test('Pi status phases use durable watcher files rather than unavailable attached sessions', () => {
  for (const phase of ['10-setup', '30-triage']) {
    const text = readFileSync(new URL(`../plugins/review-council/pi-skills/review-council-rev/phases/${phase}.md`, import.meta.url), 'utf8');
    assert.doesNotMatch(text, /watcher attached|in an attached execution/);
    assert.match(text, /status-watch\.log/);
    assert.match(text, /poll/i);
  }
});

test('manifest exposes only native Pi resources with no install lifecycle scripts', async () => {
  const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url)));
  assert.deepEqual(manifest.pi.extensions, ['./pi/rev.ts']);
  assert.deepEqual(manifest.pi.skills, ['./plugins/review-council/pi-skills/review-council-rev']);
  assert.deepEqual(manifest.pi.prompts, []);
  assert.deepEqual(manifest.pi.themes, []);
  assert.equal(manifest.scripts?.postinstall, undefined);
  for (const host of ['claude', 'codex', 'cursor']) {
    const plugin = JSON.parse(readFileSync(new URL(`../plugins/review-council/.${host}-plugin/plugin.json`, import.meta.url)));
    assert.equal(manifest.version, plugin.version, `${host} release version must match Pi`);
  }
});
