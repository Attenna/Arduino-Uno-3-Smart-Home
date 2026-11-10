"""CLI and local web demo for the voice lab.

Examples
--------
    python -m voice_lab.app --text "把客厅的灯调成蓝色"
    python -m voice_lab.app --wav samples/demo.wav
    python -m voice_lab.app --mic
    python -m voice_lab.app --serve
    python -m voice_lab.app --self-check
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from typing import Any, Optional

from .config import PC_TEST_DIR, VOICE_LAB_DIR, default_config_path, load_config
from .dialog import DialogEngine, make_engine

OUTPUT_DIR = os.path.join(VOICE_LAB_DIR, "output")
UPLOAD_DIR = os.path.join(OUTPUT_DIR, "uploads")


def _print_result(result, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return
    if result.asr:
        print(f"[ASR/{result.asr.backend}] {result.asr.text}  "
              f"({result.asr.latency_ms:.0f} ms, RTF {result.asr.rtf:.2f})")
    print(f"[用户] {result.user_text}")
    for tool in result.tool_calls:
        mark = "✓" if tool.ok else "✗"
        print(f"  {mark} {tool.name}({json.dumps(tool.arguments, ensure_ascii=False)})"
              f" → {tool.text}")
    if result.error:
        print(f"[错误] {result.error}")
    print(f"[助手] {result.reply}")
    t = result.timing
    print(f"[延迟] ASR {t.asr_ms:.0f} ms | LLM 首字 {t.llm_first_token_ms:.0f} ms / "
          f"总 {t.llm_total_ms:.0f} ms | 工具 {t.tool_ms:.0f} ms | "
          f"首音 {t.tts_first_audio_ms:.0f} ms | 整轮 {t.total_ms:.0f} ms")


def _self_check(cfg: dict) -> int:
    print("voice_lab self-check")
    print(f"  PC_Test: {PC_TEST_DIR}")
    print(f"  ffmpeg : {shutil.which('ffmpeg') or '未找到（浏览器录音/MP3 解码需要）'}")
    try:
        import sounddevice as sd
        print(f"  音频设备: 默认输入 {sd.default.device[0]} / 输出 {sd.default.device[1]}")
        print("  " + str(sd.query_devices()).splitlines()[0])
    except Exception as exc:
        print(f"  音频设备: 不可用（{exc}）")
    for section in ("asr", "llm", "tts"):
        print(f"  {section.upper()}: {cfg[section]['backend']}")
    try:
        engine = DialogEngine(cfg, tts_enabled=True, play_tts=False)
        status = engine.info()
        for key, value in status.items():
            if key != "state":
                print(f"  {key}: {value}")
        print(f"  设备状态: {status['state']}")
        ok = all(v is not False for k, v in status.items() if k.endswith("_model"))
        return 0 if ok else 1
    except Exception as exc:
        print(f"  初始化失败: {exc}")
        return 1


def _record_and_turn(engine: DialogEngine, cfg: dict, args) -> int:
    from .audio import record_until_silence, save_wav

    print(f"请说话（最多 {cfg['audio']['record_seconds']} 秒，静音 {cfg['audio']['silence_seconds']} 秒后结束）…")
    audio = record_until_silence(
        max_seconds=float(cfg["audio"]["record_seconds"]),
        sample_rate=int(cfg["audio"]["sample_rate"]),
        silence_seconds=float(cfg["audio"]["silence_seconds"]),
        threshold=float(cfg["audio"]["energy_threshold"]),
    )
    if not len(audio):
        print("没有检测到语音。")
        return 2
    path = os.path.join(OUTPUT_DIR, "mic_last.wav")
    save_wav(path, audio, int(cfg["audio"]["sample_rate"]))
    print(f"录音 {len(audio) / cfg['audio']['sample_rate']:.2f} s → {path}")
    result = engine.handle_audio(path, speak=not args.no_tts,
                                 play=not args.no_play)
    _print_result(result, args.json)
    return 0 if not result.error else 1


# ── Flask page ───────────────────────────────────────────────────────
_PAGE = r"""<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Voice Lab · 级联语音对话</title>
<style>
:root{--bg:#0b0f16;--panel:#121926;--panel2:#0f1622;--line:#253044;--txt:#e8edf7;
--dim:#8b98ad;--blue:#4f8cff;--green:#34d399;--amber:#fbbf24;--red:#f87171;--purple:#a78bfa}
*{box-sizing:border-box}
body{margin:0;min-height:100vh;background:radial-gradient(1200px 600px at 20% -10%,#173054 0%,transparent 55%),var(--bg);
color:var(--txt);font-family:system-ui,-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
header{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:16px 24px;
border-bottom:1px solid var(--line);background:#0d1420cc;backdrop-filter:blur(10px);position:sticky;top:0;z-index:5}
.logo{font-size:18px;font-weight:750;letter-spacing:.3px}
.logo span{color:var(--blue)}
.pill{font-size:12px;padding:4px 10px;border:1px solid var(--line);border-radius:99px;color:var(--dim);
white-space:nowrap}.pill b{color:var(--txt);font-weight:600}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--dim);margin-right:6px;vertical-align:0px}
main{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(300px,.8fr);gap:18px;max-width:1280px;margin:0 auto;padding:18px 24px 32px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.card{background:linear-gradient(180deg,var(--panel),var(--panel2));border:1px solid var(--line);border-radius:16px;
box-shadow:0 10px 30px #0006;overflow:hidden}
.card h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim);margin:0;padding:14px 16px;border-bottom:1px solid var(--line)}
#log{height:min(62vh,620px);overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:92%;padding:10px 13px;border-radius:13px;line-height:1.55;font-size:15px;white-space:pre-wrap;word-break:break-word;animation:in .16s ease}
@keyframes in{from{opacity:0;transform:translateY(4px)}to{opacity:1}}
.user{align-self:flex-end;background:linear-gradient(145deg,#2563eb,#1d4ed8);color:#fff;border-bottom-right-radius:4px}
.bot{align-self:flex-start;background:#182334;border:1px solid var(--line);border-bottom-left-radius:4px}
.sys{align-self:center;color:var(--dim);font-size:12.5px}
.tool{align-self:flex-start;border-left:2px solid var(--green);padding:3px 10px;color:var(--dim);
font-size:12.5px;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap;max-width:94%}
.tool.err{border-color:var(--red)}
.composer{display:flex;gap:9px;padding:12px;border-top:1px solid var(--line);background:#0e1520}
#txt{flex:1;min-width:0;background:#0a111b;border:1px solid var(--line);border-radius:12px;color:var(--txt);
padding:11px 13px;font-size:15px;outline:none}#txt:focus{border-color:var(--blue)}
button{border:1px solid var(--line);border-radius:12px;background:#162033;color:var(--txt);padding:0 15px;
font-size:14px;cursor:pointer;transition:.15s}button:hover{border-color:#3a4a66;background:#1b2941}
button:disabled{opacity:.45;cursor:wait}
#send{padding:0 18px;background:linear-gradient(145deg,#3b82f6,#1d4ed8);border:0}
#mic{width:44px;padding:0;border-radius:50%;font-size:18px;background:#162033}
#mic.rec{background:#7f1d1d;border-color:#ef4444;animation:pulse 1.1s infinite}
@keyframes pulse{50%{box-shadow:0 0 0 10px #ef444422}}
.row{display:flex;gap:10px;flex-wrap:wrap;padding:10px 14px}
.small{font-size:12px;color:var(--dim)}
.side{display:flex;flex-direction:column;gap:18px}
.state{padding:13px 15px;font-size:13.5px;line-height:1.75;color:#c7d2e5;white-space:pre-wrap}
.state b{color:var(--txt)}
.lat{padding:12px 15px 16px;display:flex;flex-direction:column;gap:8px}
.latrow{font-size:12px;color:var(--dim)}
.latrow .bar{height:7px;background:#1d2a3d;border-radius:99px;margin-top:4px;overflow:hidden}
.latrow .bar i{display:block;height:100%;border-radius:99px;background:var(--blue);width:0;transition:width .5s}
.latrow .num{float:right;color:var(--txt);font-variant-numeric:tabular-nums}
.examples{display:flex;flex-wrap:wrap;gap:7px;padding:10px 14px 14px}
.examples button{font-size:12.5px;padding:6px 10px;border-radius:99px;background:#111c2c}
.note{padding:0 15px 14px;font-size:11.5px;color:#6f7f96;line-height:1.5}
.err{color:var(--red);font-size:12.5px;padding:0 15px 12px}
</style></head><body>
<header>
  <div class="logo">Voice <span>Lab</span></div>
  <span class="pill"><span class="dot" id="statusDot"></span><b id="status">加载中</b></span>
  <span class="pill">ASR <b id="asrPill">--</b></span>
  <span class="pill">LLM <b id="llmPill">--</b></span>
  <span class="pill">TTS <b id="ttsPill">--</b></span>
  <span style="flex:1"></span>
  <label class="pill" style="cursor:pointer"><input type="checkbox" id="speak" checked> 语音播报</label>
  <button id="reset" style="font-size:12px;padding:6px 12px">重置</button>
</header>
<main>
  <section class="card">
    <h2>对话</h2>
    <div id="log"><div class="sys">说「你好」或点下面的示例指令开始。首次调用会加载本地模型，约 10–20 秒。</div></div>
    <div class="examples">
      <button data-t="把客厅的灯调成蓝色">客厅灯变蓝</button>
      <button data-t="卧室灯太亮了，调暗一点">卧室灯调暗</button>
      <button data-t="打开风扇，调到三档">风扇三档</button>
      <button data-t="现在屋里多少度？">查温度</button>
      <button data-t="切换到观影模式">观影模式</button>
      <button data-t="你好，你能做什么？">能做什么</button>
    </div>
    <div class="composer">
      <button id="mic" title="按住/点击录音">🎤</button>
      <input id="txt" placeholder="输入文字指令，或点麦克风说话…" autocomplete="off">
      <button id="send">发送</button>
    </div>
  </section>
  <aside class="side">
    <section class="card"><h2>设备状态</h2><div class="state" id="devices">--</div></section>
    <section class="card"><h2>延迟分解</h2><div class="lat" id="lat"><div class="small">完成一轮后显示。</div></div></section>
    <section class="card"><h2>说明</h2><div class="note">级联：Sherpa/Whisper ASR → 本地 Qwen2.5 或 API → edge-tts / VITS。语音从运行服务的电脑扬声器播放；页面只负责采集与展示。</div><div class="err" id="err"></div></section>
  </aside>
</main>
<script>
const $=id=>document.getElementById(id);
const log=$('log'), txt=$('txt'), err=$('err');
let recorder=null, chunks=[], busy=false;
function setStatus(s,tone){$('status').textContent=s; $('statusDot').style.background=tone||'var(--green)'}
function add(cls,text){const d=document.createElement('div'); d.className='msg '+cls; d.textContent=text; log.appendChild(d);
  log.scrollTop=log.scrollHeight; return d;}
function sys(text){const d=document.createElement('div'); d.className='msg sys'; d.textContent=text; log.appendChild(d); log.scrollTop=log.scrollHeight;}
function tool(t){const d=document.createElement('div'); d.className='msg tool '+(t.ok?'':'err');
  d.textContent=(t.ok?'✓ ':'✗ ')+t.name+' '+JSON.stringify(t.arguments)+'\n→ '+t.text; log.appendChild(d); log.scrollTop=log.scrollHeight;}
function renderDevices(s){if(!s)return; const l=s.light||{}; const lines=[];
  for(const [room,name] of [['living_room','客厅'],['bedroom','卧室'],['kitchen','厨房']]){
    const d=l[room]||{}; lines.push(`${name}灯：${d.on?'开':'关'} ${d.on?(d.color||'')+' / '+(d.brightness??'')+'%':''}`);
  }
  lines.push(`风扇：${s.fan?.on?'开 '+s.fan.speed+'档':'关'}`);
  lines.push(`门：${s.door?.open?'开':'关'}${s.door?.locked?' / 已上锁':' / 未上锁'}`);
  lines.push(`空调：${s.ac?.on?s.ac.temperature+'℃ / '+s.ac.mode:'关'}`);
  lines.push(`场景：${s.scene||'--'}  ·  温度 ${s.sensors?.temperature??'--'}℃ / 湿度 ${s.sensors?.humidity??'--'}%`);
  $('devices').textContent=lines.join('\n');}
function renderTiming(t){if(!t)return; const rows=[
  ['ASR',t.asr_ms],['LLM 首字',t.llm_first_token_ms],['LLM 总',t.llm_total_ms],['工具',t.tool_ms],
  ['首音（从开始）',t.tts_first_audio_ms],['整轮',t.total_ms]];
  const max=Math.max(1,...rows.map(r=>r[1]||0));
  $('lat').innerHTML=rows.map(([k,v])=>`<div class="latrow">${k}<span class="num">${Math.round(v||0)} ms</span><div class="bar"><i style="width:${Math.max(2,(v||0)/max*100)}%"></i></div></div>`).join('');}
function setBusy(b){busy=b; $('send').disabled=b; $('mic').disabled=b; $('txt').disabled=b; setStatus(b?'处理中…':'就绪',b?'var(--amber)':'var(--green)');}
async function api(path,opts){const r=await fetch(path,opts); const j=await r.json().catch(()=>({error:'返回不是 JSON'}));
  if(!r.ok || j.error) throw new Error(j.error||('HTTP '+r.status)); return j;}
async function turnText(text){if(busy||!text.trim())return; err.textContent=''; add('user',text); setBusy(true);
  try{const j=await api('/api/text',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({text,speak:$('speak').checked})});
    if(j.asr) sys('识别：'+j.asr.text);
    for(const t of (j.tool_calls||[]))tool(t);
    if(j.reply)add('bot',j.reply); if(j.error)add('sys','错误：'+j.error);
    renderTiming(j.timing); renderDevices(j.state);
  }catch(e){err.textContent=String(e); add('sys','请求失败：'+e);}
  finally{setBusy(false);}}
async function send(){const v=txt.value.trim(); if(!v)return; txt.value=''; await turnText(v);}
$('send').onclick=send; txt.addEventListener('keydown',e=>{if(e.key==='Enter')send()});
for(const b of document.querySelectorAll('.examples button'))b.onclick=()=>turnText(b.dataset.t);
$('reset').onclick=async()=>{try{await api('/api/reset',{method:'POST'}); log.innerHTML=''; sys('已重置。'); renderDevices(null); $('lat').innerHTML='<div class="small">完成一轮后显示。</div>';}catch(e){err.textContent=String(e)}};
async function toggleMic(){if(busy)return;
  if(recorder && recorder.state==='recording'){recorder.stop(); return;}
  try{const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    chunks=[]; recorder=new MediaRecorder(stream,{mimeType:MediaRecorder.isTypeSupported('audio/webm;codecs=opus')?'audio/webm;codecs=opus':'audio/webm'});
    recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};
    recorder.onstop=async()=>{stream.getTracks().forEach(t=>t.stop()); $('mic').classList.remove('rec');
      const blob=new Blob(chunks,{type:recorder.mimeType||'audio/webm'}); if(blob.size<1000){sys('录音太短。');return;}
      await uploadAudio(blob);};
    recorder.start(); $('mic').classList.add('rec'); setStatus('录音中…','var(--red)');
  }catch(e){err.textContent='无法打开麦克风：'+e;}}
$('mic').onclick=toggleMic;
async function uploadAudio(blob){err.textContent=''; setBusy(true); sys('录音已上传，识别中…');
  try{const fd=new FormData(); fd.append('file',blob,'speech.webm');
    const j=await api('/api/audio',{method:'POST',body:fd});
    if(j.asr)sys('识别：'+j.asr.text); add('user',j.user_text||'');
    for(const t of (j.tool_calls||[]))tool(t); if(j.reply)add('bot',j.reply);
    if(j.error)add('sys','错误：'+j.error); renderTiming(j.timing); renderDevices(j.state);
  }catch(e){err.textContent=String(e); add('sys','请求失败：'+e);}
  finally{setBusy(false);}}
async function boot(){try{const j=await api('/api/info');
  $('asrPill').textContent=j.asr; $('llmPill').textContent=j.llm; $('ttsPill').textContent=j.tts;
  $('devices').textContent=j.state;
  setStatus('就绪','var(--green)');
}catch(e){setStatus('离线','var(--red)'); err.textContent=String(e);}}
boot();
</script></body></html>"""


def create_app(engine: DialogEngine):
    from flask import Flask, jsonify, request, send_from_directory

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 24 * 1024 * 1024

    @app.get("/")
    def index():
        return _PAGE

    @app.get("/api/info")
    def info():
        return jsonify(engine.info())

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True})

    @app.post("/api/text")
    def api_text():
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text") or "").strip()
        if not text:
            return jsonify({"error": "text 不能为空"}), 400
        result = engine.handle_text(
            text,
            speak=bool(payload.get("speak", True)),
            play=bool(payload.get("play", True)),
        )
        return jsonify(result.to_dict())

    @app.post("/api/audio")
    def api_audio():
        uploaded = request.files.get("file")
        if uploaded is None:
            return jsonify({"error": "缺少 file 字段"}), 400
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        raw = os.path.join(UPLOAD_DIR, uuid.uuid4().hex + ".webm")
        uploaded.save(raw)
        wav = raw + ".16k.wav"
        try:
            from .audio import convert_to_wav16k
            convert_to_wav16k(raw, wav)
            result = engine.handle_audio(wav, speak=bool(request.form.get("speak", "1") not in ("0", "false")),
                                         play=bool(request.form.get("play", "1") not in ("0", "false")))
            return jsonify(result.to_dict())
        except Exception as exc:
            return jsonify({"error": f"音频处理失败: {exc}"}), 500
        finally:
            for path in (raw, wav):
                try:
                    os.remove(path)
                except OSError:
                    pass

    @app.post("/api/reset")
    def api_reset():
        engine.reset()
        return jsonify({"ok": True, "state": engine.home.snapshot()})

    @app.get("/audio/<path:name>")
    def audio(name: str):
        return send_from_directory(os.path.join(VOICE_LAB_DIR, "output"), name)

    return app


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="级联语音对话实验（语音识别 + LLM + 语音合成）")
    parser.add_argument("--config", default=default_config_path())
    parser.add_argument("--text", help="文本指令（跳过 ASR）")
    parser.add_argument("--wav", help="WAV/MP3/WebM 文件（走 ASR）")
    parser.add_argument("--mic", action="store_true", help="从默认麦克风录一句")
    parser.add_argument("--serve", action="store_true", help="启动本地 Web 演示")
    parser.add_argument("--self-check", action="store_true", help="检查模型/设备，不加载模型")
    parser.add_argument("--warmup", action="store_true", help="启动时预加载 ASR/LLM/TTS 权重")
    parser.add_argument("--list-mic", action="store_true")
    parser.add_argument("--asr", choices=["sherpa", "whisper"])
    parser.add_argument("--llm", choices=["hybrid", "llama_cpp", "openai", "rules"])
    parser.add_argument("--tts", choices=["edge", "sherpa", "cosyvoice", "none"])
    parser.add_argument("--no-tts", action="store_true", help="不合成语音（只显示文本）")
    parser.add_argument("--no-play", action="store_true", help="合成但不播放（评测用）")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    if args.asr:
        cfg["asr"]["backend"] = args.asr
    if args.llm:
        cfg["llm"]["backend"] = args.llm
    if args.tts:
        cfg["tts"]["backend"] = args.tts
    if args.self_check:
        return _self_check(cfg)
    if args.list_mic:
        from .audio import list_devices
        print(list_devices())
        return 0
    if args.serve:
        from flask import Flask
        engine = DialogEngine(cfg, play_tts=not args.no_play, tts_enabled=not args.no_tts)
        if args.warmup:
            print("preloading models ...", flush=True)
            print("  " + json.dumps(engine.preload(), ensure_ascii=False), flush=True)
        app = create_app(engine)
        host = args.host or cfg["server"]["host"]
        port = int(args.port or cfg["server"]["port"])
        print(f"Voice Lab: http://{host}:{port}/")
        print(f"  ASR={engine.asr.backend}  LLM={engine.llm.backend}  TTS={engine.tts.backend}")
        app.run(host=host, port=port, threaded=True, debug=False)
        return 0
    if not (args.text or args.wav or args.mic):
        parser.print_help()
        return 0
    engine = DialogEngine(cfg, play_tts=not args.no_play, tts_enabled=not args.no_tts)
    if args.warmup:
        print("preloading models ...", flush=True)
        print("  " + json.dumps(engine.preload(), ensure_ascii=False), flush=True)
    if args.mic:
        return _record_and_turn(engine, cfg, args)
    if args.wav:
        result = engine.handle_audio(args.wav, speak=not args.no_tts, play=not args.no_play)
    else:
        result = engine.handle_text(args.text, speak=not args.no_tts, play=not args.no_play)
    _print_result(result, args.json)
    return 0 if not result.error else 1


if __name__ == "__main__":
    sys.exit(main())
