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
  const context={document,crypto,console,Date,Math,performance:{now:()=>0},setInterval(){},window:{addEventListener(){}},
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
