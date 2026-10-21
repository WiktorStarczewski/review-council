// Synthetic offline SDK boundary double. It cannot produce live qualification.
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync, readdirSync} from 'node:fs';
import {pathToFileURL} from 'node:url';

const [driverPath, specPath, cwd] = process.argv.slice(2);
const driver = await import(pathToFileURL(driverPath));
assert.equal(typeof driver.runSdkSession, 'function',
  'driver must export the actual dependency-injected runSdkSession orchestration');
const spec = JSON.parse(readFileSync(specPath, 'utf8'));
const trace = [];
const raw = [];
const sdkMessages = [];
const abort = new AbortController();
const store = Object.freeze({syntheticPrivateStore:true});
const canary = 'synthetic-key-user-exception-canary';
const tick = () => new Promise(resolve => setImmediate(resolve));
const pending = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
};
const blockedStream = pending();
let pendingRead, actualReader, actualDispose;
let disposed = false;
let settled = false;
let lateEvents = 0;
let readDeliveries = 0;
let receivedOptions;
let waitResolved = false;
let waitEntered = false;
class CursorSdkError extends Error {
  constructor(message, options = {}) { super(message); Object.assign(this, options); }
}
class CursorAgentError extends CursorSdkError {}
class AuthenticationError extends CursorAgentError {}
class RateLimitError extends CursorAgentError {}
class NetworkError extends CursorAgentError {}
const errorTypes = {CursorSdkError,CursorAgentError,AuthenticationError,RateLimitError,NetworkError};
const fail = stage => {
  if (spec.failure?.stage !== stage) return;
  const ErrorType = errorTypes[spec.failure.name] ?? NetworkError;
  const error = new ErrorType(canary);
  error.name = spec.failure.name ?? 'NetworkError';
  error.status = spec.failure.status ?? 503;
  error.code = spec.failure.code ?? 'synthetic_failure';
  error.isRetryable = true;
  throw error;
};
const onRawEvent = async event => {
  if (settled) lateEvents++;
  trace.push('raw:' + event.type);
  raw.push(structuredClone(event));
  if (spec.failure?.stage === 'sink') fail('sink');
};
if (spec.readerOptions) {
  const bridge = await import(pathToFileURL(spec.readerPath));
  actualReader = bridge.createCouncilReader({
    ...spec.readerOptions, signal:abort.signal, onRead:onRawEvent,
  });
  actualDispose = bridge.disposeCouncilReader;
}
const reader = {
  description:'Read one authorized artifact or bounded source range',
  inputSchema:{type:'object',properties:{path:{type:'string'},
    offset:{type:'integer',minimum:1},limit:{type:'integer',minimum:1,maximum:240}},
    required:['path'],additionalProperties:false},
  execute:async (args, context) => {
    trace.push('reader:execute');
    assert.equal(disposed, false, 'disposed reader cannot deliver source');
    if (spec.abortAt === 'read') {
      pendingRead = pending();
      queueMicrotask(() => abort.abort());
      return pendingRead.promise;
    }
    const result = actualReader
      ? await actualReader.execute(args, context)
      : {content:[{type:'text',text:spec.readText ?? 'beta\ngamma\n'}]};
    if (!actualReader) await onRawEvent({
      type:'council_read_result',call_id:context.toolCallId,session_id:context.sessionId,
      input:args,text_sha256:createHash('sha256').update(result.content[0].text).digest('hex'),
    });
    if (disposed) throw new Error('reader_disposed');
    readDeliveries++;
    return result;
  },
};
const disposeReader = async value => {
  assert.equal(value, reader, 'controller must dispose the same installed reader');
  trace.push('reader:dispose');
  disposed = true;
  pendingRead?.reject(new Error('reader_disposed'));
  if (actualReader) await actualDispose(actualReader);
  fail('dispose');
};
const terminal = structuredClone(spec.terminal ?? null);
const run = {
  id:spec.runId ?? 'synthetic-run',
  agentId:spec.runAgentId ?? spec.agentId ?? 'synthetic-agent',status:'running',
  supports:operation => ['stream','wait','cancel','conversation'].includes(operation),
  unsupportedReason:() => undefined,
  async *stream() {
    trace.push('run:stream');
    try {
      fail('stream');
      for (const event of spec.events) {
        if (event.type === 'tool_call' && event.status === 'completed'
            && event.name === 'mcp' && event.args?.providerIdentifier === 'custom-user-tools'
            && event.args?.toolName === 'council_read') {
          await reader.execute(event.args.args,
            {toolCallId:event.call_id,sessionId:event.agent_id});
        }
        sdkMessages.push(structuredClone(event));
        yield event;
        if (spec.abortAt === 'stream') {
          queueMicrotask(() => abort.abort());
          await blockedStream.promise;
          return;
        }
      }
    } finally {
      trace.push('run:stream_closed');
    }
  },
  async wait() {
    trace.push('run:wait');
    waitEntered = true;
    if (spec.abortAt === 'wait') {
      queueMicrotask(() => abort.abort());
      await blockedStream.promise;
    }
    await tick();
    fail('wait');
    waitResolved = true;
    trace.push('run:wait_resolved');
    return terminal;
  },
  async cancel() {
    trace.push('run:cancel');
    blockedStream.resolve();
    fail('cancel');
  },
  async conversation() { throw new Error('unexpected conversation reload'); },
  onDidChangeStatus() {
    trace.push('run:subscribe');
    return () => trace.push('run:unsubscribe');
  },
};
const agent = {
  agentId:spec.agentId ?? 'synthetic-agent', model:spec.selection,
  async send(message, options) {
    trace.push('agent:send');
    assert.equal(message, spec.prompt, 'send must receive the exact frozen prompt text');
    assert.ok(options === undefined || Object.keys(options).length === 0,
      'a second per-send override cannot weaken the frozen create options');
    fail('send');
    return run;
  },
  close() { trace.push('agent:close'); fail('close'); },
  async reload() { trace.push('agent:reload'); throw new Error('reload forbidden'); },
  async getUsage() { trace.push('agent:getUsage'); throw new Error('extra usage call forbidden'); },
  async listArtifacts() { trace.push('agent:listArtifacts'); throw new Error('artifacts forbidden'); },
  async downloadArtifact() { trace.push('agent:downloadArtifact'); throw new Error('artifacts forbidden'); },
  async [Symbol.asyncDispose]() { trace.push('agent:asyncDispose'); throw new Error('use close once'); },
};
const sdk = {...errorTypes,Agent:{
  async create(options) {
    trace.push('Agent.create');
    receivedOptions = {
      model:structuredClone(options.model),keyExact:options.apiKey === canary,
      localKeys:Object.keys(options.local).sort(),cwd:options.local.cwd,
      storeExact:options.local.store === store,
      readerExact:options.local.customTools?.council_read === reader,
      settingSources:options.local.settingSources,
      enableAgentRetries:options.local.enableAgentRetries,
      customToolNames:Object.keys(options.local.customTools ?? {}),
      tools:options.tools,disallowedTools:options.disallowedTools,
      mcpServers:options.mcpServers,agents:options.agents,
      topKeys:Object.keys(options).sort(),
    };
    fail('create');
    return agent;
  },
  async resume() { trace.push('Agent.resume'); throw new Error('resume forbidden'); },
  async prompt() { trace.push('Agent.prompt'); throw new Error('hidden prompt forbidden'); },
},Cursor:{auth:{
  async login() { trace.push('Cursor.auth.login'); throw new Error('auth fallback forbidden'); },
}}};
if (spec.abortAt === 'before') abort.abort();
let outcome;
try {
  outcome = await driver.runSdkSession({
    sdk,selection:structuredClone(spec.selection),cwd,store,apiKey:canary,
    prompt:spec.prompt,reader,disposeReader,signal:abort.signal,onRawEvent,
  });
} catch {
  outcome = {uncaught:true};
}
settled = true;
blockedStream.resolve();
pendingRead?.resolve({content:[{type:'text',text:'late source must not be delivered'}]});
await tick();
await tick();
console.log(JSON.stringify({synthetic:true,outcome,trace,raw,sdkMessages,terminal,
  receivedOptions,waitEntered,waitResolved,lateEvents,readDeliveries,
  workspaceEntries:readdirSync(cwd)}));
