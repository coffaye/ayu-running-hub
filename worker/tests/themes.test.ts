import assert from 'node:assert/strict';
import test from 'node:test';
import { buildDispatchPayload, normalizeTheme, type ReportTheme } from '../src/core.ts';
import { createApp, validateGenerateBody } from '../src/index.ts';
import { RunGenerationLock } from '../src/lock.ts';
import { renderGeneratePage } from '../src/pages.ts';

test('exactly four accepted themes reach dispatch; routing fields remain rejected', () => {
  for (const theme of ['black-green','burgundy','blue','violet'] as const) {
    assert.equal(validateGenerateBody({runId:'123',theme}), '123');
    assert.equal(buildDispatchPayload('123','req',theme).inputs.theme, theme);
  }
  assert.throws(()=>validateGenerateBody({runId:'123',theme:'all'}));
  assert.throws(()=>validateGenerateBody({runId:'123',theme:'blue',branch:'master'}));
  assert.equal(normalizeTheme(), 'black-green');
});

test('same-run same-theme deduplicates, another theme conflicts, failure releases the lock', async () => {
  const data=new Map<string,unknown>();
  const lock=new RunGenerationLock({storage:{get:async <T>(key:string)=>data.get(key) as T|undefined,put:async(key,value)=>{data.set(key,value);}}});
  let count=0;const themes:ReportTheme[]=[];
  const app=createApp({createGithubClient:()=>({runExists:async()=>true,dispatch:async(_run,_req,theme)=>{count++;themes.push(theme!);return {workflowRunId:100+count,runUrl:'https://ci/run',htmlUrl:'https://ci/run'};},getWorkflowRun:async()=>({status:'queued',conclusion:null,htmlUrl:null})})});
  const env={HUB_ACTIONS_TOKEN:'test',REPORT_AUTH_USERNAME:'ayu',REPORT_AUTH_PASSWORD:'test',REPORT_GENERATION_LOCK:{idFromName:()=>({}),get:()=>lock}};
  const send=(theme:ReportTheme)=>app.fetch(new Request('https://test/api/generate',{method:'POST',headers:{authorization:'Basic '+btoa('ayu:test'),'content-type':'application/json'},body:JSON.stringify({runId:'123',theme})}),env);
  const a=await send('burgundy'),b=await send('burgundy');
  assert.equal(a.status,202);assert.equal(b.status,202);
  assert.equal((await a.json() as {workflowRunId:number}).workflowRunId,(await b.json() as {workflowRunId:number}).workflowRunId);
  assert.equal((await send('blue')).status,409);assert.equal(count,1);
  await lock.fetch(new Request('https://internal/release',{method:'POST',body:JSON.stringify({state:'failure'})}));
  assert.equal((await send('blue')).status,202);assert.deepEqual(themes,['burgundy','blue']);
});

test('generation page offers four themes and never auto-posts on GET/load',async()=>{
  const html=await renderGeneratePage('123').text();
  for(const theme of ['black-green','burgundy','blue','violet'])assert.ok(html.includes('value="'+theme+'"'));
  assert.match(html,/addEventListener\('click',generate\)/);
  assert.doesNotMatch(html,/addEventListener\('load'/);
});
