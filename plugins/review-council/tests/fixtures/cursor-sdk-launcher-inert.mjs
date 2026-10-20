// Synthetic launcher target. It neither imports an SDK nor issues qualification.
import assert from 'node:assert/strict';
import {existsSync, writeFileSync} from 'node:fs';

export async function runDriver(argv) {
  assert.equal(process.env.SYNTHETIC_LAUNCH_NONCE, 'synthetic-launch-nonce');
  assert.equal(existsSync(process.env.SYNTHETIC_LAUNCH_RECORD), false,
    'installed launcher must invoke the controller exactly once');
  writeFileSync(process.env.SYNTHETIC_LAUNCH_RECORD, JSON.stringify({
    synthetic: true, calls: 1, entry: process.argv[1], argv,
    nonce: process.env.SYNTHETIC_LAUNCH_NONCE,
  }));
  return argv[0] === 'closed-quota-fixture' ? 4 : 0;
}
