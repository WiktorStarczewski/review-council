import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { stripVTControlCharacters } from 'node:util';

const root = new URL('../', import.meta.url);
const manifest = JSON.parse(readFileSync(new URL('package.json', root), 'utf8'));
const { loadExtensions, clearExtensionCache } = await import(process.env.PI_TEST_LOADER);
const { FooterComponent } = await import(new URL('../../modes/interactive/components/footer.js', process.env.PI_TEST_LOADER));
const { initTheme } = await import(new URL('../../modes/interactive/theme/theme.js', process.env.PI_TEST_LOADER));

function footer(extension) {
  let text;
  const ctx = {
    hasUI: true,
    sessionManager: { getBranch: () => [] },
    ui: { theme: { fg: (_color, value) => value }, setStatus: (_key, value) => { text = value; } },
  };
  for (const handler of extension.handlers.get('session_start')) handler({}, ctx);
  return text;
}

test('same-process Pi reload renders updated Council code at the same installed path', async () => {
  const directory = mkdtempSync(join(tmpdir(), 'council-hot-reload-'));
  try {
    const source = new URL(manifest.pi.extensions[0], root);
    const original = readFileSync(source, 'utf8');
    const entry = join(directory, 'pi', basename(fileURLToPath(source)));
    mkdirSync(join(directory, 'pi'));
    writeFileSync(entry, original);
    const before = await loadExtensions([entry], directory);
    assert.deepEqual(before.errors, []);
    assert.equal(footer(before.extensions[0]), '⚖️ council: 🌿 ECO');

    const updated = original.replace("'council: '", "'upgraded council: '");
    assert.notEqual(updated, original);
    writeFileSync(entry, updated);
    clearExtensionCache();
    const after = await loadExtensions([entry], directory);
    assert.deepEqual(after.errors, []);
    assert.equal(footer(after.extensions[0]), '⚖️ upgraded council: 🌿 ECO',
      'Pi reload must not retain the old native ESM factory');
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test('real Pi footer preserves one visible spacing cell after the Council icon', async () => {
  initTheme('dark');
  const source = new URL(manifest.pi.extensions[0], root);
  const loaded = await loadExtensions([fileURLToPath(source)], fileURLToPath(root));
  assert.deepEqual(loaded.errors, []);
  const status = footer(loaded.extensions[0]);
  const session = {
    state: {},
    getContextUsage: () => ({ percent: 0, contextWindow: 1000 }),
    sessionManager: {
      getEntryCount: () => 0, getSessionId: () => 'test', getLeafId: () => null,
      getEntries: () => [], getCwd: () => '/tmp', getSessionName: () => undefined,
    },
  };
  const data = {
    getGitBranch: () => undefined, getAvailableProviderCount: () => 0,
    getExtensionStatuses: () => new Map([['review-council', status]]),
  };
  const rendered = stripVTControlCharacters(new FooterComponent(session, data).render(200).at(-1));
  assert.equal(rendered, '⚖️ council: 🌿 ECO');
});
