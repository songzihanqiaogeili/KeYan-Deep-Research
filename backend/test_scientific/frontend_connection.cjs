const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(process.argv[2],'utf8');
const api=source.slice(source.indexOf('async function api('),source.indexOf('async function json('));
let connected=true;
const context={state:{token:'fixture'},location:{origin:'http://127.0.0.1:8765'},setConnection:v=>connected=v,
 FormData:global.FormData,AbortController,setTimeout,clearTimeout,
 $:()=>({open:false,showModal(){}}),fetch:async()=>{throw new TypeError('Failed to fetch');}};
vm.createContext(context);vm.runInContext(api,context);
(async()=>{
 await assert.rejects(context.api('/api/runs'),e=>e.message.includes('后端')&&e.message.includes('8765'));
 assert.equal(connected,false);
 context.fetch=async()=>({ok:false,status:503,json:async()=>({detail:'检索来源暂不可用'})});
 await assert.rejects(context.api('/api/search'),e=>e.message==='检索来源暂不可用');
 assert.equal(connected,true);
 console.log('frontend transport distinction OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
