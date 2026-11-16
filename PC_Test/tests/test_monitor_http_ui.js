const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const code = fs.readFileSync('PC_Test/web/static/js/objects.js','utf8');
for (const crypto of [undefined, {}, {randomUUID:()=> 'fixture-uuid'}]) {
 test(`monitor initializes with randomUUID ${typeof crypto?.randomUUID}`, async()=>{
  const elements = new Map();
  const requested=[];
  const document={getElementById(id){
   if(!elements.has(id)) elements.set(id,{checked:false,textContent:'',replaceChildren(){},getContext(){return {clearRect(){}}}});
   return elements.get(id);
  }};
  const context={document,crypto,console,Date,Math,performance:{now:()=>0},setInterval(){},setTimeout(){},clearTimeout(){},window:{addEventListener(){}},
   fetch:async(url)=>{requested.push(url);return {ok:true,json:async()=>url.includes('/events')?[]:url.includes('/objects/status')?{loaded:true,classes:{0:'light bulb'},input_size:[640,640],provider:'Ascend310B4'}:{model_loaded:true}}}};
  vm.runInNewContext(code,context);
  await new Promise(resolve=>setImmediate(resolve));
  assert.ok(requested.includes('/api/objects/status'));
  assert.match(elements.get('status').textContent,/Ascend310B4/);
  elements.get('bulbLight').checked=true;
  elements.get('bulbLight').onchange();
  assert.match(elements.get('bulbLightStatus').textContent,/开始检测后生效/);
 });
}

test('pending stream falls back to sequential snapshots without starting inference', async()=>{
 const elements=new Map(), timers=[], requests=[];
 const context={document:{getElementById(id){
  if(!elements.has(id)) elements.set(id,{checked:true,textContent:'',naturalWidth:0,src:'',getAttribute(){return this.src;},replaceChildren(){},getContext(){return {clearRect(){}}}});
  return elements.get(id);
 }},Date,Math,performance:{now:()=>0},setInterval(){},setTimeout(fn,ms){timers.push({fn,ms});return timers.length;},clearTimeout(){},window:{addEventListener(){}},
 fetch:async(url)=>{requests.push(url);return {ok:true,json:async()=>url.includes('/events')?[]:url.includes('/objects/status')?{loaded:true,classes:{},input_size:[640,640],provider:'test'}:{model_loaded:true}}}};
 vm.runInNewContext(code,context);
 timers.find(t=>t.ms===8000).fn();
 assert.match(elements.get('liveVideo').src,/^\/api\/camera\/snapshot\?t=/);
 elements.get('liveVideo').onload();
 assert.match(elements.get('videoStatus').textContent,/连续快照模式/);
 assert.ok(timers.some(t=>t.ms===250));
 assert.ok(!requests.includes('/api/monitor/session'));
});

test('lease conflict explains inference ownership and leaves camera running', async()=>{
 const elements=new Map();
 const context={document:{getElementById(id){
  if(!elements.has(id)) elements.set(id,{checked:true,textContent:'',src:'',getAttribute(){return this.src;},replaceChildren(){},getContext(){return {clearRect(){}}}});
  return elements.get(id);
 }},Date,Math,performance:{now:()=>0},setInterval(){},setTimeout(){},clearTimeout(){},window:{addEventListener(){}},
 fetch:async(url)=>({ok:!url.includes('/session'),status:url.includes('/session')?409:200,json:async()=>url.includes('/session')?{error:'busy'}:url.includes('/events')?[]:url.includes('/objects/status')?{loaded:true,classes:{},input_size:[640,640],provider:'test'}:{model_loaded:true}})};
 vm.runInNewContext(code,context);
 elements.get('live').onclick();
 await new Promise(resolve=>setImmediate(resolve));
 assert.match(elements.get('message').textContent,/本页仍可看视频/);
 assert.match(elements.get('liveVideo').src,/^\/api\/camera\/stream/);
});
