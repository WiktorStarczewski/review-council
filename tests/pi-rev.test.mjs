import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const extensionURL = new URL('../pi/rev.mjs', import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));

async function harness({ idle = true, active = false } = {}) {
  assert.ok(existsSync(extensionURL), 'native /rev extension must exist');
  const { default: extension } = await import(extensionURL);
  const commands = new Map();
  const messages = [];
  const notices = [];
  const executions = [];
  const pi = {
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
    hasUI: true,
    cwd: '/tmp/reviewed project',
    ui: { notify: (...args) => notices.push(args) },
  };
  const previous = process.env.REV_ACTIVE;
  if (active) process.env.REV_ACTIVE = '1';
  try {
    return { commands, messages, notices, executions, ctx,
      invoke: (args) => commands.get('rev').handler(args, ctx) };
  } finally {
    if (previous === undefined) delete process.env.REV_ACTIVE;
    else process.env.REV_ACTIVE = previous;
  }
}

test('registers only /rev and binds the installed Pi workflow without shell interpretation', async () => {
  const h = await harness();
  assert.deepEqual([...h.commands.keys()], ['rev']);
  const args = 'https://github.com/o/r/pull/12 --read-only "x y" $(touch /tmp/never)';
  await h.invoke(args);
  assert.equal(h.messages.length, 1);
  assert.ok(h.messages[0].message.includes(root + 'plugins/review-council/pi-skills/review-council-rev/SKILL.md'));
  assert.ok(h.messages[0].message.endsWith(args));
  assert.ok(h.messages[0].message.includes('REVIEW_COUNCIL_HOST=pi'));
  assert.equal(h.executions.length, 0);
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

test('manifest exposes only native Pi resources with no install lifecycle scripts', async () => {
  const manifest = JSON.parse(readFileSync(new URL('../package.json', import.meta.url)));
  assert.deepEqual(manifest.pi.extensions, ['./pi/rev.mjs']);
  assert.deepEqual(manifest.pi.skills, ['./plugins/review-council/pi-skills/review-council-rev']);
  assert.deepEqual(manifest.pi.prompts, []);
  assert.deepEqual(manifest.pi.themes, []);
  assert.equal(manifest.scripts?.postinstall, undefined);
});
