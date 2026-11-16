const el = id => document.getElementById(id);
let running = false, busy = false;
const labels = {'drone': '无人机', 'drones': '无人机', 'fire extinguisher': '灭火器', 'light bulb': '灯泡'};
const displayLabel = label => labels[label] || label;
async function api(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || '请求失败');
  return data;
}
async function events() {
  const rows = await api('/api/objects/events');
  el('events').replaceChildren();
  if (!rows.length) el('events').textContent = '暂无命中事件';
  for (const row of rows) {
    const article = document.createElement('article');
    article.textContent = new Date(row.time).toLocaleString() + ' · ' + row.result.detections.map(d => `${displayLabel(d.label)} ${(d.confidence*100).toFixed(1)}%`).join('、');
    if (row.image) { const image = document.createElement('img'); image.src = row.image; article.append(document.createElement('br'), image); }
    el('events').append(article);
  }
}
// Monitoring ownership ID is not an authentication credential. LAN HTTP may lack randomUUID.
const client = typeof globalThis.crypto?.randomUUID === 'function'
  ? globalThis.crypto.randomUUID()
  : `monitor-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
let resultVersion = '', expiry = 0, polling = false, previewUrl = null, generation = 0;
const video = el('liveVideo');
function clearBoxes() {
  const canvas = el('view');
  canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
}
function useLiveVideo() {
  if (previewUrl) { URL.revokeObjectURL(previewUrl); previewUrl = null; }
  if (video.getAttribute('src') !== '/api/camera/stream') video.src = '/api/camera/stream';
  clearBoxes();
}
function showResult(data, ttl = 5000) {
  const canvas = el('view'); canvas.width = data.width; canvas.height = data.height;
  const ctx = canvas.getContext('2d'); ctx.lineWidth = 3; ctx.font = '18px sans-serif';
  ctx.strokeStyle = '#e27c42'; ctx.fillStyle = '#e27c42';
  for (const d of data.detections) {
    const [x,y,r,b] = d.box; ctx.strokeRect(x,y,r-x,b-y);
    ctx.fillText(`${displayLabel(d.label)} ${(d.confidence*100).toFixed(0)}%`,x,Math.max(20,y-6));
  }
  const faces = data.face_result;
  ctx.strokeStyle = '#528fbd'; ctx.fillStyle = '#528fbd';
  for (const face of faces?.faces || []) {
    const b = face.bbox; ctx.strokeRect(b.x1,b.y1,b.x2-b.x1,b.y2-b.y1);
    ctx.fillText(face.person_name || '陌生人 / 未匹配',b.x1,Math.max(20,b.y1-6));
  }
  el('faceResult').textContent = !data.faces_enabled ? '本页人脸识别已关闭' :
    faces?.error || (faces?.faces?.length ? faces.faces.map(f => f.person_name || '陌生人 / 未匹配').join('、') : '本帧未检测到人脸');
  el('result').textContent = data.detections.length ? data.detections.map(d => `${displayLabel(d.label)} ${(d.confidence*100).toFixed(1)}%`).join('；') : (data.objects_enabled ? '本帧未检测到目标' : '本页物体检测已关闭');
  el('bulbLightStatus').textContent = data.bulb_light?.message || '等待检测';
  el('message').textContent = `${new Date(data.time).toLocaleTimeString()} · 处理耗时 ${data.inference_ms} ms · 蓝色人脸 / 橙色物体`;
  expiry = performance.now() + ttl;
  if (data.event_id) events().catch(e => el('message').textContent = e.message);
}
function options() {
  return {client, active:running, faces:el('enableFaces').checked, objects:el('enableObjects').checked,
    evidence:el('evidence').checked, bulb_light:el('bulbLight').checked};
}
async function updateSession() {
  await api('/api/monitor/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(options())});
}
async function setRunning(value) {
  generation++;
  running = value;
  try { await updateSession(); }
  catch (e) { running = false; throw e; }
  el('live').textContent = running ? '停止连续检测' : '开始连续检测';
  el('once').disabled = el('upload').disabled = running;
  clearBoxes(); resultVersion = ''; expiry = 0;
  if (running) { useLiveVideo(); el('message').textContent = '视频播放中，等待后台检测结果'; }
}
async function poll() {
  if (!running || polling) return;
  polling = true;
  const requestedGeneration = generation;
  try {
    const state = await api('/api/monitor/result');
    if (!running || requestedGeneration !== generation) return;
    if (state.error) { clearBoxes(); el('message').textContent = state.error; }
    if (state.result && state.result.time !== resultVersion) {
      resultVersion = state.result.time;
      showResult(state.result, Math.max(0,state.ttl_ms-state.age_ms));
    }
    if (!state.result) clearBoxes();
  } catch(e) { clearBoxes(); el('message').textContent = e.message; }
  finally { polling = false; }
}
async function detect(upload=false) {
  if (busy || running) return;
  busy=true; el('once').disabled=el('upload').disabled=true;
  try {
    const body=new FormData();
    if (upload) {
      const file=el('file').files[0]; if (!file) throw new Error('请先选择图片');
      body.append('image',file);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl=URL.createObjectURL(file); video.src=previewUrl; await video.decode();
    } else useLiveVideo();
    for (const [key,value] of Object.entries(options())) body.append(key,String(value));
    const data=await api('/api/monitor/detect',{method:'POST',body});
    showResult(data);
  } catch(e) { clearBoxes();el('message').textContent=e.message; }
  finally { busy=false;el('once').disabled=el('upload').disabled=running; }
}
el('once').onclick=()=>detect();el('upload').onclick=()=>detect(true);
el('live').onclick=()=>setRunning(!running).catch(e=>el('message').textContent=e.message);
el('refresh').onclick=()=>events().catch(e=>el('message').textContent=e.message);
for (const id of ['enableFaces','enableObjects','evidence','bulbLight']) {
  el(id).onchange=()=>{
    generation++;clearBoxes();resultVersion='';expiry=0;
    if (id === 'bulbLight') el('bulbLightStatus').textContent = el('bulbLight').checked ? (running ? '联动已启用，等待灯泡检测结果' : '联动已勾选，开始检测后生效') : '灯泡开灯联动已关闭';
    if(running) updateSession().catch(e=>el('message').textContent=e.message);
  };
}
setInterval(poll,500);
setInterval(()=>{ if(running) updateSession().catch(e=>{clearBoxes();el('message').textContent=e.message;}); },5000);
setInterval(()=>{
  if(expiry && performance.now()>expiry){ clearBoxes();expiry=0;el('result').textContent='结果已过期';el('faceResult').textContent='结果已过期';el('message').textContent='检测结果已过期，等待新结果'; }
},200);
window.addEventListener('pagehide',()=>{
  if(running) fetch('/api/monitor/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...options(),active:false}),keepalive:true});
});
let reconnectTimer = null;
video.onload = () => {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
  if (!running && !previewUrl) el('message').textContent = '摄像头实时画面已连接，可开始检测';
};
video.onerror = () => {
  clearBoxes();
  if (previewUrl) { el('message').textContent = '图片无法显示，请重新选择图片'; return; }
  el('message').textContent = '摄像头画面暂时不可用，正在重新连接…';
  if (!reconnectTimer) reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    if (!previewUrl) video.src = '/api/camera/stream?t=' + Date.now();
  }, 3000);
};
if (video.complete && video.naturalWidth > 0) video.onload();
api('/api/face/status').then(s => { el('faceResult').textContent = s.model_loaded ? '人脸模型已加载，等待检测' : '人脸模型未就绪'; }).catch(e => el('faceResult').textContent = e.message);
api('/api/objects/status').then(s => { el('status').textContent = s.loaded ? `已加载 · ${Object.values(s.classes).map(displayLabel).join('、')} · ${s.input_size.join(' × ')} · ${s.provider}` : s.error; }).catch(e => el('status').textContent = e.message);
events().catch(e => el('message').textContent = e.message);
