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
async function detect(upload = false) {
  if (busy) return;
  busy = true;
  el('once').disabled = el('upload').disabled = true;
  let preview;
  try {
    const body = new FormData();
    if (upload) {
      const file = el('file').files[0];
      if (!file) throw new Error('请先选择图片');
      body.append('image', file); preview = URL.createObjectURL(file);
    }
    body.append('evidence', String(el('evidence').checked));
    const data = await api('/api/objects/detect', {method:'POST', body});
    // 摄像头画面使用检测时同一快照，避免框与后续帧错位。
    if (!upload) preview = data.preview;
    if (preview) {
      const img = new Image(); img.src = preview; await img.decode();
      const canvas = el('view'); canvas.width = data.width; canvas.height = data.height;
      const ctx = canvas.getContext('2d'); ctx.drawImage(img,0,0);
      ctx.strokeStyle = '#e27c42'; ctx.fillStyle = '#e27c42'; ctx.lineWidth = 3; ctx.font = '18px sans-serif';
      for (const d of data.detections) { const [x,y,r,b] = d.box; ctx.strokeRect(x,y,r-x,b-y); ctx.fillText(`${displayLabel(d.label)} ${(d.confidence*100).toFixed(0)}%`,x,Math.max(20,y-6)); }
    }
    el('message').textContent = `${new Date(data.time).toLocaleTimeString()} · ${data.inference_ms} ms`;
    el('result').textContent = data.detections.length ? data.detections.map(d => `${displayLabel(d.label)} ${(d.confidence*100).toFixed(1)}% [${d.box.join(', ')}]`).join('；') : '本帧未检测到目标';
    if (data.event_id) await events();
  } catch (error) { el('message').textContent = error.message; }
  finally { if (upload && preview) URL.revokeObjectURL(preview); busy = false; el('once').disabled = el('upload').disabled = false; }
}
el('once').onclick = () => detect(); el('upload').onclick = () => detect(true); el('refresh').onclick = () => events().catch(e => el('message').textContent = e.message);
el('live').onclick = () => { running = !running; el('live').textContent = running ? '停止连续检测' : '开始连续检测'; if (running) detect(); };
setInterval(() => { if (running) detect(); },3000);
api('/api/objects/status').then(s => { el('status').textContent = s.loaded ? `已加载 · ${Object.values(s.classes).map(displayLabel).join('、')} · ${s.input_size.join(' × ')} · ${s.provider}` : s.error; }).catch(e => el('status').textContent = e.message);
events().catch(e => el('message').textContent = e.message);
