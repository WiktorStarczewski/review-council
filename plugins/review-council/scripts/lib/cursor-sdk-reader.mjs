import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {isDeepStrictEqual} from 'node:util';

const HELPER = fileURLToPath(new URL('./cursor-read-helper.py', import.meta.url));
const PYTHON = 'python3';
const READ_TIMEOUT_MS = 60_000;
const readers = new WeakMap();
const digest = text => createHash('sha256').update(text).digest('hex');
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const schema = {
  type:'object', properties:{
    path:{type:'string'}, offset:{type:'integer',minimum:1},
    limit:{type:'integer',minimum:1,maximum:240},
  }, required:['path'], additionalProperties:false,
};

function references(state, enabled) {
  const method = enabled ? 'ref' : 'unref';
  state.child?.[method]();
  for (const stream of [state.child?.stdin,state.child?.stdout,state.child?.stderr]) {
    stream?.[method]?.();
  }
}

function terminate(child, signal) {
  try {
    if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, signal);
    else child.kill(signal);
  } catch {
    child.kill(signal);
  }
}

function stop(state, reason) {
  if (!state.reason) state.reason = reason;
  clearTimeout(state.timer);
  const pending = [...(state.active ? [state.active] : []),...state.queue];
  state.active = null;
  state.queue = [];
  for (const job of pending) job.reject(new Error(state.reason));
  if (state.stopping) return state.stopping;
  state.signal?.removeEventListener?.('abort', state.abort);
  const child = state.child;
  state.stopping = new Promise(resolve => {
    if (!child || state.exited) {
      resolve();
      return;
    }
    references(state, true);
    let force;
    child.once('close', () => {
      clearTimeout(force);
      resolve();
    });
    child.stdin.destroy();
    terminate(child, 'SIGTERM');
    force = setTimeout(() => terminate(child, 'SIGKILL'), 500);
  });
  return state.stopping;
}

function validateResponse(state, job, response) {
  if (!object(response) || Object.keys(response).sort().join(',') !== 'meta,text'
      || typeof response.text !== 'string' || !object(response.meta)) throw new Error();
  const meta = response.meta;
  const keys = new Set(['input','path','source','text_sha256','prompt_sha256',
    'manifest_sha256','seat','snapshot_tree','blob_oid']);
  if (Object.keys(meta).some(key => !keys.has(key)) || !isDeepStrictEqual(meta.input, job.input)
      || typeof meta.path !== 'string' || !['snapshot','artifact','context','dependency'].includes(meta.source)
      || meta.text_sha256 !== digest(response.text) || meta.prompt_sha256 !== state.promptSha256
      || meta.manifest_sha256 !== (state.manifestSha256 ?? null) || meta.seat !== (state.seat ?? null)) {
    throw new Error();
  }
  if (meta.source === 'snapshot' && (!/^[0-9a-f]{40}(?:[0-9a-f]{24})?$/.test(meta.blob_oid)
      || !/^[0-9a-f]{40}(?:[0-9a-f]{24})?$/.test(meta.snapshot_tree))) throw new Error();
}

async function delivered(state, line) {
  const job = state.active;
  if (state.reason || !job || state.delivering) {
    await stop(state, 'reader_refused');
    return;
  }
  state.delivering = true;
  let response;
  try {
    response = JSON.parse(line);
    validateResponse(state, job, response);
  } catch {
    await stop(state, 'reader_refused');
    return;
  }
  try {
    if (state.onRead) await state.onRead({
      type:'council_read_result', call_id:job.callId, session_id:job.sessionId,
      input:job.input, text_sha256:response.meta.text_sha256, meta:response.meta,
    });
  } catch {
    await stop(state, 'reader_callback_failed');
    return;
  }
  if (state.reason) return;
  clearTimeout(state.timer);
  state.active = null;
  state.delivering = false;
  job.resolve({content:[{type:'text',text:response.text}]});
  pump(state);
}

function start(state) {
  if (state.child) return;
  const args = [HELPER,'--serve','--root',state.root,'--session',state.session,
    '--prompt',state.prompt,'--prompt-sha256',state.promptSha256];
  if (state.manifest !== undefined) {
    args.push('--manifest',state.manifest,'--manifest-sha256',state.manifestSha256,'--seat',state.seat);
  }
  if (state.depsRoot !== undefined) args.push('--deps-root',state.depsRoot);
  const child = spawn(PYTHON, args, {shell:false,stdio:['pipe','pipe','pipe'],
    detached:process.platform !== 'win32',windowsHide:true});
  state.child = child;
  child.stdout.setEncoding('utf8');
  child.stdout.on('data', chunk => {
    state.buffer += chunk;
    while (state.buffer.includes('\n')) {
      const end = state.buffer.indexOf('\n');
      const line = state.buffer.slice(0,end);
      state.buffer = state.buffer.slice(end + 1);
      void delivered(state, line);
    }
  });
  child.stderr.on('data', () => {});
  child.stdin.on('error', () => { void stop(state, 'reader_refused'); });
  child.on('error', () => { void stop(state, 'reader_refused'); });
  child.on('close', () => {
    state.exited = true;
    if (!state.reason) void stop(state, 'reader_refused');
  });
}

function pump(state) {
  if (state.reason || state.active) return;
  if (!state.queue.length) {
    references(state, false);
    return;
  }
  state.active = state.queue.shift();
  try {
    start(state);
    references(state, true);
    state.timer = setTimeout(() => { void stop(state, 'reader_refused'); }, READ_TIMEOUT_MS);
    state.child.stdin.write(state.active.wire + '\n');
  } catch {
    void stop(state, 'reader_refused');
  }
}

export function createCouncilReader(options) {
  const state = {queue:[],active:null,buffer:'',usedIds:new Set()};
  try {
    const allowed = new Set(['root','session','prompt','manifest','manifestSha256','seat',
      'depsRoot','promptSha256','signal','onRead']);
    if (!object(options) || Object.keys(options).some(key => !allowed.has(key))) throw new Error();
    for (const key of ['root','session','prompt']) {
      if (typeof options[key] !== 'string' || !options[key]) throw new Error();
      state[key] = options[key];
    }
    for (const key of ['manifest','manifestSha256','seat','depsRoot']) {
      if (options[key] !== undefined && (typeof options[key] !== 'string' || !options[key])) {
        throw new Error();
      }
      state[key] = options[key];
    }
    if ([state.manifest,state.manifestSha256,state.seat].filter(value => value !== undefined).length % 3) {
      throw new Error();
    }
    state.promptSha256 = digest(readFileSync(state.prompt));
    if (options.promptSha256 !== undefined && options.promptSha256 !== state.promptSha256) throw new Error();
    if (options.onRead !== undefined && typeof options.onRead !== 'function') throw new Error();
    state.onRead = options.onRead;
    state.signal = options.signal;
    state.abort = () => { void stop(state, 'reader_cancelled'); };
    if (state.signal) {
      if (typeof state.signal.aborted !== 'boolean'
          || typeof state.signal.addEventListener !== 'function') throw new Error();
      if (state.signal.aborted) state.reason = 'reader_cancelled';
      else state.signal.addEventListener('abort', state.abort, {once:true});
    }
  } catch {
    state.reason = 'reader_refused';
  }
  const reader = {
    description:'Read one authorized artifact or bounded source range', inputSchema:structuredClone(schema),
    execute(input, context) {
      if (state.reason) return Promise.reject(new Error(state.reason));
      if (!context || typeof context.toolCallId !== 'string' || !context.toolCallId
          || typeof context.sessionId !== 'string' || !context.sessionId
          || state.usedIds.has(context.toolCallId)
          || (state.sessionId !== undefined && state.sessionId !== context.sessionId)) {
        return Promise.reject(new Error('reader_context_invalid'));
      }
      let wire;
      let captured;
      try {
        wire = JSON.stringify(input);
        captured = JSON.parse(wire);
      } catch {
        return Promise.reject(new Error('reader_refused'));
      }
      state.usedIds.add(context.toolCallId);
      state.sessionId = context.sessionId;
      return new Promise((resolve,reject) => {
        state.queue.push({input:captured,wire,callId:context.toolCallId,
          sessionId:context.sessionId,resolve,reject});
        pump(state);
      });
    },
  };
  readers.set(reader, state);
  return reader;
}

export async function disposeCouncilReader(reader) {
  const state = readers.get(reader);
  if (state) await stop(state, 'reader_disposed');
}
