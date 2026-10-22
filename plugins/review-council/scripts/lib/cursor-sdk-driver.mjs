import {spawn} from 'node:child_process';
import {createHash, createHmac, randomBytes, timingSafeEqual} from 'node:crypto';
import {constants, closeSync, existsSync, fstatSync, lstatSync, mkdirSync, mkdtempSync,
  openSync, readFileSync, readdirSync, realpathSync, renameSync,
  writeFileSync, writeSync} from 'node:fs';
import {dirname, join, resolve} from 'node:path';
import {fileURLToPath, pathToFileURL} from 'node:url';
import {isDeepStrictEqual} from 'node:util';
import {createCouncilReader, disposeCouncilReader} from './cursor-sdk-reader.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const SDK_VERSION = '1.0.38';
const MAX_EVENTS = 4096;
const MAX_RAW_BYTES = 32 * 1024 * 1024;
const MAX_READS = 160;
const ATTEMPT_MS = 30 * 60 * 1000;
const LOGIN_MS = 5 * 60 * 1000;
const hash = value => createHash('sha256').update(value).digest('hex');
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);

export function buildSeatOptions({selection,cwd,store,apiKey,reader}) {
  return {
    model:structuredClone(selection),apiKey,
    local:{cwd,store,settingSources:[],enableAgentRetries:false,customTools:{council_read:reader}},
    mcpServers:{},agents:{},tools:['mcp'],
    disallowedTools:['task','shell','read','edit','delete','webSearch','webFetch'],
  };
}

function classified(error, sdk) {
  if ((sdk.AuthenticationError && error instanceof sdk.AuthenticationError) || error?.status === 401) {
    return {exitCode:3,reason:'sdk_unauthenticated'};
  }
  if ((sdk.RateLimitError && error instanceof sdk.RateLimitError) || error?.status === 429) {
    return {exitCode:4,reason:'sdk_quota'};
  }
  return {exitCode:1,reason:'sdk_failed'};
}

export async function runSdkSession({sdk,selection,cwd,store,apiKey,prompt,reader,
  disposeReader,signal,onRawEvent}) {
  let agent, run, outcome, active = true, aborted = signal?.aborted === true;
  let rejectAbort;
  const closed = new Set(), cancelled = new Set();
  const interrupted = new Promise((_, reject) => { rejectAbort = reject; });
  interrupted.catch(() => {});
  const abort = () => { aborted = true; active = false; rejectAbort(new Error('cancelled')); };
  signal?.addEventListener('abort', abort, {once:true});
  const wait = promise => Promise.race([promise,interrupted]);
  const close = value => {
    if (!value || closed.has(value)) return;
    closed.add(value);
    value.close();
  };
  const cancel = async value => {
    if (!value || cancelled.has(value)) return;
    cancelled.add(value);
    await value.cancel();
  };
  const acquired = (promise, cleanup, record) => Promise.resolve(promise).then(value => {
    record(value);
    if (!active || aborted) {
      Promise.resolve().then(() => cleanup(value)).catch(() => {});
      throw new Error('cancelled');
    }
    return value;
  });
  const bounded = async operation => {
    let timer;
    try {
      await Promise.race([Promise.resolve().then(operation),new Promise((_,reject) => {
        timer = setTimeout(() => reject(new Error('cleanup_timeout')),500);
      })]);
      return true;
    } catch { return false; }
    finally { clearTimeout(timer); }
  };
  const emit = async event => {
    if (!active || aborted) throw new Error('cancelled');
    await wait(Promise.resolve().then(() => onRawEvent(event)));
    if (!active || aborted) throw new Error('cancelled');
  };
  try {
    if (aborted) throw new Error('cancelled');
    agent = await wait(acquired(sdk.Agent.create(
      buildSeatOptions({selection,cwd,store,apiKey,reader})),close,value => { agent = value; }));
    if (aborted) throw new Error('cancelled');
    run = await wait(acquired(agent.send(prompt),cancel,value => { run = value; }));
    if (aborted) throw new Error('cancelled');
    const iterator = run.stream()[Symbol.asyncIterator]();
    while (true) {
      const next = await wait(iterator.next());
      if (next.done) break;
      await emit(next.value);
    }
    const terminal = await wait(run.wait());
    if (object(terminal)) {
      await emit({type:'result',...terminal,agent_id:agent.agentId,run_id:run.id});
    }
    if (!object(terminal) || !agent.agentId || !run.id || run.agentId !== agent.agentId
        || terminal.id !== run.id || !isDeepStrictEqual(terminal.model,selection)
        || terminal.status !== 'finished') {
      outcome = {exitCode:terminal?.status === 'error' ? 1 : 2,
        reason:terminal?.status === 'error' ? 'sdk_run_failed' : 'sdk_terminal_invalid'};
      if (object(terminal)) outcome.terminal = terminal;
    } else outcome = {exitCode:0,reason:'transport_finished',terminal};
  } catch (error) {
    outcome = aborted ? {exitCode:2,reason:'sdk_cancelled'} : classified(error,sdk);
  } finally {
    active = false;
    signal?.removeEventListener('abort', abort);
    if (outcome?.exitCode !== 0 && run) await bounded(() => cancel(run));
    const disposed = await bounded(() => disposeReader(reader));
    const agentClosed = await bounded(() => close(agent));
    if ((!disposed || !agentClosed) && outcome?.exitCode === 0) {
      outcome = {exitCode:1,reason:'sdk_cleanup_failed'};
    }
  }
  return outcome;
}

class Refusal extends Error {
  constructor(reason, exitCode) { super(reason); this.reason = reason; this.exitCode = exitCode; }
}

function refuse(reason, exitCode) { throw new Refusal(reason,exitCode); }

export function driverFailure(error) {
  return error instanceof Refusal ? {reason:error.reason,exitCode:error.exitCode}
    : {reason:'sdk_initialization_failed',exitCode:1};
}

function bytes(path, ceiling = 32 * 1024 * 1024, privateFile = false) {
  path = resolve(path);
  if (realpathSync(path) !== path) refuse('input_invalid',6);
  const descriptor = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = fstatSync(descriptor);
    if (!info.isFile() || info.nlink !== 1 || info.size > ceiling
        || (privateFile && (info.uid !== process.getuid() || (info.mode & 0o077)))) {
      refuse('input_invalid',6);
    }
    return readFileSync(descriptor);
  } finally { closeSync(descriptor); }
}

const json = path => JSON.parse(bytes(path).toString('utf8'));
const outputJSON = (path,value) => writeFileSync(path,JSON.stringify(value) + '\n',
  {mode:0o600,flag:'wx'});

function command(executable, args, options = {}) {
  return new Promise((yes,no) => {
    const child = spawn(executable,args,{shell:false,stdio:['pipe','pipe','pipe'],...options});
    let stdout = '', size = 0, failed = false;
    const timer = setTimeout(() => { failed = true; child.kill('SIGKILL'); },60_000);
    child.stdout.on('data',chunk => {
      size += chunk.length;
      if (size > MAX_RAW_BYTES) { failed = true; child.kill('SIGKILL'); }
      else stdout += chunk;
    });
    child.stderr.on('data',() => {});
    child.stdin.on('error', error => { if (error?.code !== 'EPIPE') failed = true; });
    child.on('error',() => { failed = true; });
    child.on('close',code => {
      clearTimeout(timer);
      if (failed || code !== 0) no(new Error('controller_command_failed'));
      else yes(stdout);
    });
    child.stdin.end(options.input ?? '');
  });
}

function selection(value) {
  if (!object(value) || Object.keys(value).some(key => !['id','params','maxMode'].includes(key))
      || typeof value.id !== 'string' || !/^grok[-.a-zA-Z0-9_]{1,120}$/.test(value.id)
      || (value.maxMode !== undefined && typeof value.maxMode !== 'boolean')
      || !Array.isArray(value.params) || value.params.length > 16
      || value.params.some(row => !object(row) || Object.keys(row).sort().join(',') !== 'id,value'
        || typeof row.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(row.id)
        || typeof row.value !== 'string' || !/^[a-zA-Z0-9_.-]{1,64}$/.test(row.value))
      || new Set(value.params.map(row => row.id)).size !== value.params.length
      || !value.params.some(row => ['reasoning','reasoning_effort','effort'].includes(row.id)
        && row.value === 'xhigh')) refuse('selection_invalid',6);
  return value;
}

function argumentsFor(argv, allowed) {
  const parsed = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    if (!allowed.includes(key) || key in parsed || !argv[index + 1]) refuse('arguments_invalid',6);
    parsed[key] = argv[index + 1];
  }
  if (allowed.some(key => !(key in parsed))) refuse('arguments_invalid',6);
  return parsed;
}

async function runtime() {
  const directory = process.env.REVIEW_COUNCIL_CURSOR_SDK_RUNTIME;
  if (!directory || !existsSync(directory)) refuse('runtime_missing',5);
  if (Number(process.versions.node.split('.')[0]) < 22
      || (Number(process.versions.node.split('.')[0]) === 22
        && Number(process.versions.node.split('.')[1]) < 13)) refuse('node_version_unavailable',5);
  let identity;
  try { identity = JSON.parse(await command('python3',[join(HERE,'../cursor-sdk/verify-runtime.py'),directory])); }
  catch { refuse('runtime_invalid',5); }
  if (identity.platform !== process.platform || identity.arch !== process.arch) {
    refuse('runtime_platform_unavailable',5);
  }
  return {...identity,directory:realpathSync(directory),runtime_sha256:hash(JSON.stringify({
    verified_runtime:identity.runtime_sha256,node:process.version,
    platform:process.platform,arch:process.arch,
  }))};
}

async function sdkImport(identity) {
  try {
    return await import(pathToFileURL(join(identity.directory,'node_modules/@cursor/sdk/dist/esm/index.js')));
  } catch { refuse('sdk_import_failed',5); }
}

function sanitizeCatalog(models) {
  const text = value => {
    if (typeof value !== 'string' || !value || value.length > 256
        || /[\x00-\x1f\x7f]/.test(value)) refuse('catalog_invalid',5);
    return value;
  };
  const list = (value, mapper, limit = 128) => {
    if (!Array.isArray(value) || value.length > limit) refuse('catalog_invalid',5);
    return value.map(mapper);
  };
  const params = value => list(value,row => ({id:text(row.id),value:text(row.value)}),16);
  const result = list(models,row => {
    if (!object(row)) refuse('catalog_invalid',5);
    const item = {id:text(row.id),displayName:text(row.displayName)};
    if (row.description !== undefined) item.description = text(row.description);
    if (row.aliases !== undefined) item.aliases = list(row.aliases,text,32);
    if (row.parameters !== undefined) item.parameters = list(row.parameters,parameter => {
      const value = {id:text(parameter.id),values:list(parameter.values,entry => {
        const option = {value:text(entry.value)};
        if (entry.displayName !== undefined) option.displayName = text(entry.displayName);
        return option;
      },32)};
      if (parameter.displayName !== undefined) value.displayName = text(parameter.displayName);
      return value;
    },16);
    if (row.variants !== undefined) item.variants = list(row.variants,variant => {
      const value = {params:params(variant.params),displayName:text(variant.displayName)};
      if (variant.description !== undefined) value.description = text(variant.description);
      for (const flag of ['isDefault','isMaxMode']) {
        if (variant[flag] !== undefined) {
          if (typeof variant[flag] !== 'boolean') refuse('catalog_invalid',5);
          value[flag] = variant[flag];
        }
      }
      return value;
    });
    return item;
  },512);
  if (new Set(result.map(row => row.id)).size !== result.length
      || Buffer.byteLength(JSON.stringify(result)) > 1024 * 1024) refuse('catalog_invalid',5);
  return result;
}

async function catalog(sdk, identity, apiKey) {
  let available;
  try { available = await sdk.Cursor.models.list({apiKey}); }
  catch (error) {
    if (classified(error,sdk).exitCode === 3) {
      process.stderr.write('Sign in with: node "$PLUGIN/scripts/lib/cursor-sdk-driver.mjs" login\n');
      refuse('sdk_unauthenticated',5);
    }
    throw error;
  }
  const models = sanitizeCatalog(available);
  return {version:1,sdk_version:SDK_VERSION,runtime_sha256:identity.runtime_sha256,models};
}

async function login(sdk) {
  const abort = new AbortController();
  const cancel = () => abort.abort();
  const interrupted = new Promise((_,reject) => {
    abort.signal.addEventListener('abort',() => reject(new Refusal('sdk_login_cancelled',3)),{once:true});
  });
  const timer = setTimeout(cancel,LOGIN_MS);
  process.on('SIGINT',cancel);
  process.on('SIGTERM',cancel);
  try {
    await Promise.race([
      Promise.resolve().then(() => sdk.Cursor.auth.login({signal:abort.signal})),interrupted,
    ]);
    if (abort.signal.aborted) refuse('sdk_login_cancelled',3);
    process.stdout.write(JSON.stringify({version:1,status:'signed-in'}) + '\n');
  } catch (error) {
    if (error instanceof Refusal) throw error;
    const failure = classified(error,sdk);
    refuse(failure.reason,failure.exitCode);
  } finally {
    clearTimeout(timer);
    process.removeListener('SIGINT',cancel);
    process.removeListener('SIGTERM',cancel);
  }
}

async function authStatus(sdk, apiKey) {
  let status = 'environment-override-present';
  if (apiKey === undefined) {
    let current;
    try { current = await sdk.Cursor.auth.status(); }
    catch (error) {
      const failure = classified(error,sdk);
      refuse(failure.reason,failure.exitCode);
    }
    if (!object(current) || !['logged-in','logged-out'].includes(current.status)) {
      refuse('sdk_auth_status_invalid',1);
    }
    status = current.status === 'logged-in' ? 'sdk-login-present' : 'sdk-login-absent';
  }
  process.stdout.write(JSON.stringify({version:1,status}) + '\n');
}

function exactSelection(selected, models) {
  const model = models.find(row => row.id === selected.id);
  if (!model) refuse('model_unavailable',5);
  if (selected.params.some(parameter => !model.parameters?.some(definition =>
    definition.id === parameter.id && definition.values.some(row => row.value === parameter.value)))) {
    refuse('effort_unavailable',5);
  }
  const variants = model.variants?.filter(variant => isDeepStrictEqual(variant.params,selected.params));
  if (variants?.length !== 1 || Boolean(variants[0].isMaxMode) !== Boolean(selected.maxMode)) {
    refuse('selection_unavailable',5);
  }
}

function key(identity, create = false) {
  const path = join(identity.directory,'.qualification-key');
  if (create && !existsSync(path)) writeFileSync(path,randomBytes(32),{mode:0o600,flag:'wx'});
  const value = bytes(path,32,true);
  if (value.length !== 32) refuse('qualification_invalid',2);
  return value;
}

function mac(value, secret) {
  return createHmac('sha256',secret).update(JSON.stringify(value)).digest('hex');
}

async function qualification(path, identity, selected) {
  try {
    const receipt = JSON.parse(bytes(path,2 * 1024 * 1024,true));
    const {signature,...body} = receipt;
    if (body.version !== 1 || body.kind !== 'cursor-sdk-live-qualification'
        || body.sdk_version !== SDK_VERSION || body.runtime_sha256 !== identity.runtime_sha256
        || body.platform !== identity.platform || body.arch !== identity.arch
        || body.helper !== identity.helper || body.effort !== 'xhigh'
        || !isDeepStrictEqual(body.selection,selected) || !object(body.evidence)
        || typeof signature !== 'string' || !/^[0-9a-f]{64}$/.test(signature)
        || !timingSafeEqual(Buffer.from(signature,'hex'),Buffer.from(mac(body,key(identity)),'hex'))) {
      throw new Error();
    }
    for (const [name,digest] of Object.entries(body.evidence)) {
      if (!/^[0-9a-f]{64}$/.test(digest) || hash(bytes(name)) !== digest) throw new Error();
    }
    if (!body.evidence[body.raw] || !body.evidence[body.audit] || !body.evidence[body.result]
        || !body.evidence[body.manifest] || !body.evidence[body.prompt]) throw new Error();
    await audit(body.binding,body.raw,body.result,
      body.audit + '.recheck-' + randomBytes(6).toString('hex'),true);
    return body;
  } catch { refuse('qualification_invalid',2); }
}

async function audit(binding, raw, result, output, requireFull = false) {
  const args = [join(HERE,'review-read-audit.py'),'audit','--adapter','cursor-sdk',
    '--raw',raw,'--result',result,'--prompt',binding.prompt,'--root',binding.root,
    '--session',binding.session,'--out',output];
  if (binding.depsRoot) args.push('--deps',binding.depsRoot);
  try {
    await command('python3',args);
    const report = json(output);
    if (report.status !== 'valid' || report.evidence_scoped !== true
        || typeof report.narrow !== 'boolean' || (requireFull && report.narrow)
        || report.violations?.length || report.stream_sha256 !== hash(bytes(raw))) throw new Error();
    return report;
  } catch { refuse('sdk_proof_invalid',2); }
}

async function frozenBinding(args) {
  const session = realpathSync(args['--session']);
  const label = args['--round'], seat = args['--seat'];
  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(label) || !/^[a-zA-Z0-9_-]{1,80}$/.test(seat)) {
    refuse('assignment_invalid',6);
  }
  const root = realpathSync(args['--root']), prompt = realpathSync(args['--prompt']);
  const manifest = join(session,`r${label}-evidence.manifest.json`);
  const manifestRaw = bytes(manifest);
  const document = JSON.parse(manifestRaw);
  const roster = json(join(session,'roster.json'));
  const matches = roster.seats?.filter(row => row.seat === seat);
  if (prompt !== join(session,`r${label}-${seat}.prompt.md`) || matches?.length !== 1
      || matches[0].adapter !== 'cursor-sdk' || matches[0].effort !== 'xhigh'
      || document.assignments?.[seat]?.adapter !== 'cursor-sdk') refuse('assignment_invalid',6);
  const chosen = selection(matches[0].model_selection);
  if (matches[0].model !== chosen.id || (process.env.MODEL && process.env.MODEL !== chosen.id)
      || (process.env.EFFORT && process.env.EFFORT !== 'xhigh')) refuse('assignment_invalid',6);
  return {session,label,seat,root,prompt,manifest,manifestSha256:hash(manifestRaw),
    selection:chosen,depsRoot:document.dependency_view?.path};
}

async function attempt(sdk, binding, directory, raw, result, apiKey, emitRaw = false) {
  const abort = new AbortController();
  const cancel = () => abort.abort();
  let timer, descriptor, reader, sessionOwnsReader = false;
  let events = 0, size = 0, reads = 0;
  const onRawEvent = async event => {
    if (abort.signal.aborted) throw new Error('cancelled');
    const wire = JSON.stringify(event) + '\n';
    events++; size += Buffer.byteLength(wire);
    if (event.type === 'council_read_result') reads++;
    if (events > MAX_EVENTS || size > MAX_RAW_BYTES || reads > MAX_READS) {
      abort.abort(); throw new Error('capacity_exceeded');
    }
    writeSync(descriptor,wire);
    if (emitRaw) process.stdout.write(wire);
  };
  try {
    descriptor = openSync(raw,constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL,0o600);
    timer = setTimeout(() => abort.abort(),ATTEMPT_MS);
    process.once('SIGTERM',cancel);
    process.once('SIGINT',cancel);
    const cwd = join(directory,'cwd'), storePath = join(directory,'store');
    mkdirSync(cwd,{mode:0o700}); mkdirSync(storePath,{mode:0o700});
    const store = new sdk.JsonlLocalAgentStore(storePath);
    const prompt = bytes(binding.prompt).toString('utf8');
    reader = createCouncilReader({root:binding.root,session:binding.session,prompt:binding.prompt,
      manifest:binding.manifest,manifestSha256:binding.manifestSha256,seat:binding.seat,
      ...(binding.depsRoot ? {depsRoot:binding.depsRoot} : {}),signal:abort.signal,onRead:onRawEvent});
    sessionOwnsReader = true;
    const outcome = await runSdkSession({sdk,selection:binding.selection,cwd,
      store,apiKey,prompt,reader,disposeReader:disposeCouncilReader,
      signal:abort.signal,onRawEvent});
    if (outcome.exitCode !== 0) refuse(outcome.reason,outcome.exitCode);
    let resultCreated = false;
    try {
      const findings = JSON.parse(outcome.terminal.result);
      outputJSON(result,findings);
      resultCreated = true;
      await command('python3',[join(HERE,'validate-findings.py'),result]);
    } catch {
      if (resultCreated) renameSync(result,result + '.invalid-' + randomBytes(6).toString('hex'));
      refuse('sdk_findings_invalid',2);
    }
    return outcome;
  } finally {
    clearTimeout(timer);
    if (descriptor !== undefined) closeSync(descriptor);
    if (reader && !sessionOwnsReader) await disposeCouncilReader(reader);
    process.removeListener('SIGTERM',cancel); process.removeListener('SIGINT',cancel);
  }
}

async function probeFixture(directory, selected) {
  const root = join(directory,'source'), session = join(directory,'session');
  mkdirSync(root,{mode:0o700}); mkdirSync(session,{mode:0o700});
  const environment = {...process.env,REV_PATCH_CHUNKS:'1',REV_SOURCE_CONTEXT:'1'};
  const git = (...args) => command('git',['-C',root,...args],{env:environment});
  await git('init','-q');
  const nonce = randomBytes(24).toString('hex');
  const source = value => Array.from({length:110},(_,index) =>
    `def qualification_${String(index).padStart(3,'0')}():\n    return "${value}-${nonce}-${'x'.repeat(320)}"\n\n`).join('')
    + 'def qualification_required_source():\n'
    + Array.from({length:180},(_,index) =>
      `    value_${index} = "${value}-${nonce}-${'x'.repeat(96)}"\n`).join('')
    + '    return value_179\n';
  writeFileSync(join(root,'sample.py'),source('before'),{mode:0o600});
  await git('add','sample.py');
  const tree = (await git('write-tree')).trim();
  const base = (await git('commit-tree',tree,'-m','Qualification source baseline')).trim();
  await git('update-ref','HEAD',base);
  writeFileSync(join(root,'sample.py'),source('after'),{mode:0o600});
  const quote = value => "'" + value.replaceAll("'","'\\''") + "'";
  writeFileSync(join(session,'scope.env'),`REV_BASE=${quote(base)}\nREV_ROOT=${quote(root)}\nREV_SCOPE=branch\n`,{mode:0o600});
  for (const name of ['files.txt','untracked.txt']) writeFileSync(join(session,name),'',{mode:0o600});
  outputJSON(join(session,'roster.json'),{seats:['grok','control2','control3','control4'].map(seat =>
    ({seat,adapter:'cursor-sdk',lab:'xai',model:selected.id,effort:'xhigh',model_selection:selected}))});
  await command('python3',[join(HERE,'../rev-evidence.py'),'prepare',session,'1',
    '--phase','discovery','--full-seat','grok'],{env:environment});
  const manifest = join(session,'r1-evidence.manifest.json');
  const document = json(manifest);
  await command('bash',[join(HERE,'../rev-prompt.sh'),session,'1','grok',
    document.assignments.grok.bundle,
    'Qualification fixture only. Use custom-user-tools council_read. Read every assigned artifact completely and every required bounded source range. Return exactly one JSON object with summary and findings; findings may be empty.',
    '--evidence',manifest],{env:environment});
  return frozenBinding({'--session':session,'--round':'1','--seat':'grok',
    '--root':root,'--prompt':join(session,'r1-grok.prompt.md')});
}

async function probe(args, sdk, identity, apiKey) {
  let requested;
  try { requested = json(args['--selection']); }
  catch { refuse('selection_invalid',6); }
  if (!object(requested) || Object.keys(requested).sort().join(',') !== 'effort,selection'
      || requested.effort !== 'xhigh') refuse('selection_invalid',6);
  const selected = selection(requested.selection);
  let inventory;
  try { inventory = await catalog(sdk,identity,apiKey); }
  catch (error) { refuse(error instanceof Refusal ? error.reason : 'catalog_unavailable',5); }
  exactSelection(selected,inventory.models);
  const output = resolve(args['--output']), parent = dirname(output), info = lstatSync(parent);
  if (realpathSync(parent) !== parent || !info.isDirectory() || info.uid !== process.getuid()
      || (info.mode & 0o077) || existsSync(output)) refuse('receipt_path_invalid',6);
  const directory = mkdtempSync(join(parent,'.cursor-sdk-probe-'));
  const binding = await probeFixture(directory,selected);
  const raw = join(binding.session,'r1-grok.stream.ndjson');
  const result = join(binding.session,'r1-grok.json');
  const auditPath = join(binding.session,'r1-grok.read-audit.json');
  try { await attempt(sdk,binding,directory,raw,result,apiKey); }
  catch (error) {
    if (error instanceof Refusal && [3,4].includes(error.exitCode)) {
      refuse('qualification_unavailable',5);
    }
    throw error;
  }
  const report = await audit(binding,raw,result,auditPath,true);
  const events = bytes(raw).toString('utf8').trimEnd().split('\n').map(line => JSON.parse(line));
  if (!events.some(event => event.type === 'tool_call' && event.name === 'mcp'
      && event.args?.providerIdentifier === 'custom-user-tools' && event.args?.toolName === 'council_read'
      && event.status === 'completed') || !events.some(event => event.type === 'council_read_result')
      || report.required_source_ranges_covered < 1 || !report.post_index_source_ranges?.length) {
    refuse('qualification_proof_incomplete',2);
  }
  const evidence = {};
  const collect = path => {
    const info = lstatSync(path);
    if (info.isSymbolicLink()) refuse('qualification_proof_invalid',2);
    if (info.isDirectory()) {
      if (path.endsWith('/.git')) return;
      for (const name of readdirSync(path)) collect(join(path,name));
    } else if (info.isFile()) evidence[path] = hash(bytes(path));
    else refuse('qualification_proof_invalid',2);
  };
  collect(binding.session);
  evidence[join(binding.root,'sample.py')] = hash(bytes(join(binding.root,'sample.py')));
  const body = {version:1,kind:'cursor-sdk-live-qualification',sdk_version:SDK_VERSION,
    runtime_sha256:identity.runtime_sha256,platform:identity.platform,arch:identity.arch,
    helper:identity.helper,selection:selected,effort:'xhigh',created_at:new Date().toISOString(),
    raw,result,audit:auditPath,prompt:binding.prompt,manifest:binding.manifest,binding,evidence,
    capacity:{events:MAX_EVENTS,raw_bytes:MAX_RAW_BYTES,reader_calls:MAX_READS,timeout_ms:ATTEMPT_MS},
    provenance:{transport:'Cursor',model_lineage:['Cursor','SpaceXAI'],laboratory:'xai'}};
  outputJSON(output,{...body,signature:mac(body,key(identity,true))});
  process.stdout.write(JSON.stringify({version:1,status:'qualified',receipt_sha256:hash(bytes(output))}) + '\n');
}

export async function runDriver(argv) {
  const [operation,...rest] = argv;
  if (!['login','auth-status','catalog','probe','seat'].includes(operation)) refuse('command_invalid',6);
  let args, binding;
  if (operation === 'seat') {
    args = argumentsFor(rest,['--session','--round','--seat','--prompt','--root']);
    try { binding = await frozenBinding(args); }
    catch { refuse('assignment_invalid',6); }
    const path = process.env.REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION;
    if (!path || !existsSync(path)) refuse('qualification_missing',2);
    try {
      const receipt = JSON.parse(bytes(path,2 * 1024 * 1024,true));
      const {signature,...body} = receipt;
      if (body.kind !== 'cursor-sdk-live-qualification' || body.version !== 1
          || typeof signature !== 'string' || !/^[0-9a-f]{64}$/.test(signature)
          || !timingSafeEqual(Buffer.from(signature,'hex'),Buffer.from(mac(body,key({
            directory:process.env.REVIEW_COUNCIL_CURSOR_SDK_RUNTIME,
          })),'hex'))) throw new Error();
    } catch { refuse('qualification_invalid',2); }
  } else if (operation === 'probe') args = argumentsFor(rest,['--selection','--output']);
  else if (rest.length) refuse('arguments_invalid',6);
  const identity = await runtime();
  if (operation === 'seat') {
    await qualification(process.env.REVIEW_COUNCIL_CURSOR_SDK_QUALIFICATION,identity,binding.selection);
    try {
      await command('python3',[join(HERE,'review-read-audit.py'),'validate-prompt',
        '--root',binding.root,'--session',binding.session,'--manifest',binding.manifest,
        '--seat',binding.seat,'--prompt',binding.prompt]);
    } catch { refuse('assignment_invalid',6); }
  }
  const launcher = join(identity.directory,'launch.mjs');
  if (realpathSync(process.argv[1]) !== launcher) {
    const code = await new Promise(resolveCode => {
      const child = spawn(process.execPath,[launcher,fileURLToPath(import.meta.url),...argv],
        {shell:false,stdio:'inherit'});
      let deadline, grace, cancelled = false, finished = false;
      const signals = [];
      const finish = value => {
        if (finished) return;
        finished = true;
        clearTimeout(deadline);
        clearTimeout(grace);
        for (const [name,forward] of signals) process.removeListener(name,forward);
        resolveCode(cancelled ? (operation === 'login' ? 3 : 2) : Number.isInteger(value) ? value : 1);
      };
      const cancel = name => {
        if (finished || cancelled) return;
        cancelled = true;
        clearTimeout(deadline);
        grace = setTimeout(() => { child.kill('SIGKILL'); },operation === 'login' ? 500 : 2000);
        child.kill(name);
      };
      if (['login','probe','seat'].includes(operation)) {
        for (const name of ['SIGINT','SIGTERM']) {
          const forward = () => cancel(name);
          process.on(name,forward);
          signals.push([name,forward]);
        }
        deadline = setTimeout(() => cancel('SIGTERM'),operation === 'login' ? LOGIN_MS : ATTEMPT_MS);
      }
      child.on('error',() => finish(1));
      child.on('close',finish);
    });
    process.exitCode = code;
    return;
  }
  const override = process.env.CURSOR_API_KEY;
  const apiKey = override?.trim() ? override : undefined;
  delete process.env.CURSOR_API_KEY;
  delete process.env.CURSOR_AUTH_TOKEN;
  const sdk = await sdkImport(identity);
  if (operation === 'login') { await login(sdk); return; }
  if (operation === 'auth-status') { await authStatus(sdk,apiKey); return; }
  if (operation === 'catalog') {
    try { process.stdout.write(JSON.stringify(await catalog(sdk,identity,apiKey)) + '\n'); }
    catch (error) { refuse(error instanceof Refusal ? error.reason : 'catalog_unavailable',5); }
    return;
  }
  if (operation === 'probe') { await probe(args,sdk,identity,apiKey); return; }
  const stem = join(binding.session,`r${binding.label}-${binding.seat}`);
  const raw = stem + '.stream.ndjson', result = stem + '.json';
  const directory = mkdtempSync(join(binding.session,'.cursor-sdk-attempt-'));
  await attempt(sdk,binding,directory,raw,result,apiKey,true);
  try { await audit(binding,raw,result,stem + '.read-audit.json'); }
  catch (error) {
    renameSync(result,result + '.audit-invalid-' + randomBytes(6).toString('hex'));
    throw error;
  }
}

const isMain = import.meta.main ?? (
  !process.execArgv.some(argument => /^(?:--(?:eval|print)(?:=|$)|-[ep])/.test(argument))
  && process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)
);
if (isMain) {
  runDriver(process.argv.slice(2)).catch(error => {
    const failure = driverFailure(error);
    process.stderr.write(failure.reason + '\n');
    process.exitCode = failure.exitCode;
  });
}
