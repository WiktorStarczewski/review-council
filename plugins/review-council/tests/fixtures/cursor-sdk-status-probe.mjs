import {createHash} from 'node:crypto';
import {dirname,join} from 'node:path';

Agent.create = async options => {
  auth(options);
  const directory = dirname(options.local.cwd), session = join(directory,'session');
  const manifest = JSON.parse(readFileSync(join(session,'r1-evidence.manifest.json'),'utf8'));
  const assignment = manifest.assignments.grok, context = manifest.source_context.seats.grok;
  const prompt = readFileSync(join(session,'r1-grok.prompt.md'),'utf8');
  const source = join(directory,'source/sample.py');
  const sourceHash = () => createHash('sha256').update(readFileSync(source)).digest('hex');
  const agentId = 'synthetic-status-agent', id = 'synthetic-status-run';
  const requests = [];
  const artifact = name => requests.push({path:join(session,name)});
  for (const chunk of manifest.patch_sets[assignment.patch_set].chunks) artifact(chunk.artifact);
  for (const shard of context.shards) artifact(shard.artifact);
  for (const required of context.required_source_ranges) {
    for (const segment of required.segments) artifact(segment.artifact);
  }
  artifact('r1-evidence.md');
  const target = /^Required post-index original-source target: (.+):(\d+)-(\d+) tree (\w+) blob (\w+) content SHA-256 (\w+) reasons /m.exec(prompt);
  if (!target) throw new Error('synthetic-probe-target-missing');
  requests.push({path:target[1],offset:Number(target[2]),limit:Number(target[3])-Number(target[2])+1});
  record('Agent.create',{...keyShape(options),model:options.model,cwd:options.local.cwd,
    storeDirectory:options.local.store.directory,settingSources:options.local.settingSources,
    retries:options.local.enableAgentRetries,tools:options.tools,
    disallowedTools:options.disallowedTools,mcpServers:options.mcpServers,agents:options.agents,
    customTools:Object.keys(options.local.customTools),sourceBefore:sourceHash(),requests});
  return {agentId,async send() {
    record('agent.send');
    return {id,agentId,async *stream() {
      yield {type:'status',agent_id:agentId,run_id:id,status:'RUNNING'};
      for (const [index,request] of requests.entries()) {
        const callId = `mcp-call-fixture-0000-0000-0000-${index}\nuser_tool-council_read-${index}_0`;
        const running = {type:'tool_call',agent_id:agentId,run_id:id,call_id:callId,
          name:'mcp',status:'running',args:{providerIdentifier:'custom-user-tools',
            toolName:'council_read',args:request}};
        yield running;
        const response = await options.local.customTools.council_read.execute(request,
          {toolCallId:callId,sessionId:agentId});
        if (!Array.isArray(response.content) || response.content.length !== 1
            || response.content[0].type !== 'text' || typeof response.content[0].text !== 'string') {
          throw new Error('synthetic-reader-response-invalid');
        }
        const payload = {content:[{text:{text:response.content[0].text}}],isError:false};
        yield {...running,status:'completed',result:{status:'success',value:payload}};
      }
      yield {type:'status',agent_id:agentId,run_id:id,status:'FINISHED'};
    },async wait() {
      const terminal = {id,status:'finished',model:options.model,
        result:'{"summary":"Synthetic fixture checked","findings":[]}'};
      record('run.wait',{terminal,sourceAfter:sourceHash()});
      return terminal;
    },async cancel() { record('run.cancel'); }};
  },close() { record('agent.close'); }};
};
