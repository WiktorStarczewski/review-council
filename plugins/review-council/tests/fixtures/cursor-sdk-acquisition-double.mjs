// Synthetic acquisition promises cannot provide source or live qualification.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const [driverPath, specPath, cwd, stage, late] = process.argv.slice(2);
const driver = await import(pathToFileURL(driverPath));
assert.equal(typeof driver.runSdkSession, 'function');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const tick = () => new Promise(resolve => setImmediate(resolve));
const pending = () => {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return {promise, resolve};
};
async function exercise(blocked) {
  const trace = [];
  const raw = [];
  const acquired = pending();
  const controller = new AbortController();
  let settled = false;
  let lateEvents = 0;
  const run = {
    id:'synthetic-run', agentId:'synthetic-agent', status:'running',
    supports:operation => ['stream', 'wait', 'cancel', 'conversation'].includes(operation),
    unsupportedReason:() => undefined,
    async *stream() { trace.push('run:stream'); },
    async wait() { trace.push('run:wait'); return spec.terminal; },
    async cancel() { trace.push('run:cancel'); },
    async conversation() { throw new Error('forbidden conversation'); },
    onDidChangeStatus() { return () => {}; },
  };
  const agent = {
    agentId:'synthetic-agent', model:spec.selection,
    async send(message, options) {
      trace.push('agent:send');
      assert.equal(message, spec.prompt);
      assert.ok(options === undefined || Object.keys(options).length === 0);
      if (blocked && stage === 'send') {
        queueMicrotask(() => controller.abort());
        return acquired.promise;
      }
      return run;
    },
    close() { trace.push('agent:close'); },
    async reload() { throw new Error('forbidden reload'); },
    async getUsage() { throw new Error('forbidden extra call'); },
    async listArtifacts() { throw new Error('forbidden artifact call'); },
    async downloadArtifact() { throw new Error('forbidden artifact call'); },
    async [Symbol.asyncDispose]() { throw new Error('close must be used exactly once'); },
  };
  const reader = {execute:async () => { throw new Error('unexpected source request'); }};
  const store = Object.freeze({syntheticPrivateStore:true});
  class CursorSdkError extends Error {}
  class CursorAgentError extends CursorSdkError {}
  class AuthenticationError extends CursorAgentError {}
  class RateLimitError extends CursorAgentError {}
  class NetworkError extends CursorAgentError {}
  const sdk = {CursorSdkError, CursorAgentError, AuthenticationError, RateLimitError, NetworkError, Agent:{
    async create(options) {
      trace.push('Agent.create');
      assert.deepEqual(options.model, spec.selection);
      assert.equal(options.local.store, store);
      assert.equal(options.local.customTools.council_read, reader);
      assert.equal(options.apiKey, 'synthetic-acquisition-key');
      assert.equal(options.local.enableAgentRetries, false);
      if (blocked && stage === 'create') {
        queueMicrotask(() => controller.abort());
        return acquired.promise;
      }
      return agent;
    },
    async resume() { throw new Error('forbidden resume'); },
    async prompt() { throw new Error('forbidden hidden turn'); },
  }};
  let timer;
  let outcome;
  try {
    const attempt = driver.runSdkSession({
      sdk, selection:spec.selection, cwd, store, apiKey:'synthetic-acquisition-key',
      prompt:spec.prompt, reader, signal:controller.signal,
      disposeReader:async value => {
        assert.equal(value, reader);
        trace.push('reader:dispose');
      },
      onRawEvent:async event => {
        if (settled) lateEvents++;
        raw.push(event);
      },
    });
    outcome = await Promise.race([attempt, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('acquisition abort exceeded 1500 ms')), 1500);
    })]);
    settled = true;
  } finally {
    clearTimeout(timer);
  }
  const beforeLate = [...trace];
  if (blocked && late === 'late') {
    acquired.resolve(stage === 'create' ? agent : run);
    await tick();
    await tick();
  }
  return {outcome, trace, beforeLate, raw, lateEvents};
}
const control = await exercise(false);
const observed = await exercise(true);
console.log(JSON.stringify({synthetic:true, control, observed}));
