const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const fn=source.slice(source.indexOf('async function loadEvents('),source.indexOf('async function poll('));
const list={children:[],append(v){this.children.push(v);},get firstChild(){return {remove:()=>this.children.shift()};}};
const state={run:{id:'r'},cursor:0,events:[],eventGeneration:1};let requests=0;
const all=Array.from({length:251},(_,i)=>({sequence:i+1,type:i===250?'pipeline_stage_completed':'queued',stage:i===250?'finalize':undefined,time:new Date(0).toISOString()}));
const context={state,Date,eventLabels:{},stageLabels:{finalize:'交付'},document:{querySelector:()=>({})},
 $:id=>id==='events'?list:{},element:()=>({}),renderPipelineDiagnostics(){},
 json:async path=>{requests++;await new Promise(r=>setTimeout(r,1));return all.filter(e=>e.sequence>Number(path.split('after=')[1])).slice(0,200);}};
vm.createContext(context);vm.runInContext(fn,context);
(async()=>{
 await Promise.all([context.loadEvents('r'),context.loadEvents('r')]);
 assert.equal(state.events.length,251);assert.equal(state.cursor,251);assert.equal(requests,2);
 assert.equal(state.events.at(-1).stage,'finalize');
 state.cursor=0;state.events=[];state.eventGeneration++;
 context.json=async()=>{state.run={id:'other'};return all.slice(0,200);};
 await context.loadEvents('r');assert.equal(state.events.length,0);
 console.log('event pagination, concurrency and switched-run guards OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
