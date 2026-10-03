"""voice_assistant.py — PC 端语音交互模式主编排（Sherpa-ONNX 语音前端）

流程：
    麦克风 → Sherpa-ONNX 双引擎（sherpa_listener.SherpaListener）
        KWS（zipformer 关键词检测）→ 命中「Hey Bota」→ 切 COMMAND + 提示音
        流式 Paraformer ASR + 端点检测 → 整句指令
        FOLLOWUP：回答后 8s 追问窗口，无需再唤醒
    用户指令 → LLM 流式 + 工具调用（默认硅基流动云端 API，可切阿里云百炼或本地 qwen_server.py）
        delta.content → 按句切分喂 TTS（边生成边播）
        delta.tool_calls → 经 web 硬件网关 HTTP 调用（本进程不碰串口/MCP）
    回复文本 → sherpa-onnx VITS 本地流式播放

控制边界：
    串口由 web 服务（run_web.py）拉起的 mcp_home_server 独占。本进程所有硬件
    动作都走网关 HTTP API：GET /api/hardware/tools 取工具 schema，
    POST /api/hardware/tool 执行。web 既是执行者也是记账者，仪表盘状态/历史/
    「手动优先」事件与语音天然一致，无需任何二段式回传。

启动：
    py -3.13 voice_assistant.py                     # 用 voice_config.yaml
    py -3.13 voice_assistant.py --gateway http://127.0.0.1:5000
    py -3.13 voice_assistant.py --self-check
    py -3.13 voice_assistant.py --test-llm "开红灯"
    py -3.13 voice_assistant.py --kws-repl
    py -3.13 voice_assistant.py --list-mic
"""
import argparse
import asyncio
import copy
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

import yaml

# 同目录模块（tts_player 依赖 sounddevice，惰性导入以便依赖不全时自检可运行）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PC_TEST_DIR = os.path.dirname(os.path.abspath(__file__))

SILICONFLOW_BASE = "https://api.siliconflow.cn/v1"
DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# mode → 云端 OpenAI 兼容端点；不在表里的 mode 视为本地服务（base_url 由配置给）
CLOUD_LLM_BASES = {"siliconflow": SILICONFLOW_BASE, "dashscope": DASHSCOPE_BASE}

# 云端 LLM 单次「两段数据之间」的最大间隔（秒），llm.timeout_s 可覆盖
LLM_TIMEOUT_S = 30.0


# ==================== 硬件网关客户端（web :5000）====================

class HardwareGateway:
    """web 硬件网关的 HTTP 客户端：不碰串口/MCP，一切硬件动作经 HTTP 下发。

    base_url 解析优先级：--gateway > 环境变量 SMART_HOME_WEB_URL >
    voice_config.yaml gateway.url > http://127.0.0.1:5000。
    """

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._headers = {"Authorization": "Bearer " + os.environ.get("SMART_HOME_SERVICE_TOKEN", "")}

    def _post(self, path: str, payload: dict, timeout: float) -> tuple[bool, str]:
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={**self._headers, "Content-Type": "application/json",
                     "X-Trigger-Source": "voice"},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
            except Exception:
                return False, f"error: 网关 HTTP {e.code}"
            return False, f"error: {body.get('error') or body.get('result') or f'网关 HTTP {e.code}'}"
        except Exception as e:
            return False, f"error: 硬件网关不可达（{self.base_url}）: {e}"
        ok = bool(body.get("ok"))
        text = str(body.get("result") or body.get("error") or "ok")
        return ok, text

    def fetch_tools(self) -> list:
        """拉取全部硬件工具的 OpenAI function schema；网关未就绪时抛异常。"""
        req = urllib.request.Request(f"{self.base_url}/api/hardware/tools", headers=self._headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description") or "",
                "parameters": t.get("parameters")
                or {"type": "object", "properties": {}},
            },
        } for t in data.get("tools", [])]

    def call(self, name: str, arguments: dict,
             timeout: float = 20.0) -> tuple[bool, str]:
        return self._post("/api/hardware/tool",
                          {"name": name, "arguments": arguments,
                           "source": "voice", "timeout": timeout},
                          timeout + 5)

    def health(self) -> tuple[bool, dict]:
        """web /api/status 摘要（在线状态 + 串口健康度），自检/状态页用。"""
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{self.base_url}/api/status", headers=self._headers),
                                        timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            hb = data.get("hardware_bridge") or {}
            return True, {"online": bool(hb.get("online")),
                          "last_error": hb.get("last_error")}
        except Exception as e:
            return False, {"error": str(e)}


# ==================== 事件总线（SSE 对话实况）====================

class EventBus:
    """线程安全的发布/订阅：音频回调线程与 asyncio 主循环都往这里发事件，
    每个 SSE 连接一个队列；另留环形历史，新连接先补发再实时跟进。"""

    HISTORY_MAX = 200

    def __init__(self):
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self._history: list[dict] = []

    def publish(self, etype: str, **fields) -> None:
        event = {"type": etype, "ts": time.time()}
        event.update(fields)
        with self._lock:
            self._history.append(event)
            if len(self._history) > self.HISTORY_MAX:
                del self._history[:len(self._history) - self.HISTORY_MAX]
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)   # 满则丢：实况流宁缺毋滥，不拖慢音频回调
            except queue.Full:
                pass

    def subscribe(self) -> tuple[queue.Queue, list]:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self._lock:
            self._subs.append(q)
            history = list(self._history)
        return q, history

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


# ==================== 配置加载 ====================

DEFAULT_CONFIG = {
    "gateway": {"url": "http://127.0.0.1:5000"},
    "llm": {"mode": "siliconflow",
            "base_url": SILICONFLOW_BASE,
            "api_key": None,
            "model": "Qwen/Qwen3.5-4B",
            "timeout_s": LLM_TIMEOUT_S,
            "system_prompt": "你是智能家居语音助手。",
            "local": {"gguf_path": "models/qwen/qwen2.5-3b-instruct-q4_k_m.gguf",
                      "n_ctx": 8192, "n_threads": 0, "n_gpu_layers": 0, "port": 8000}},
    "sherpa": {
        "provider": "cpu",
        "num_threads": 2,
        "kws": {"model_dir": "models/sherpa/kws",
                "keywords_file": "models/sherpa/kws/keywords.txt",
                "keywords_score": 1.5, "keywords_threshold": 0.25},
        "asr": {"model_dir": "models/sherpa/asr",
                "rule1_silence": 2.4, "rule2_silence": 1.2, "rule3_utt_len": 20.0,
                "hotwords_file": "models/sherpa/asr/hotwords.txt", "hotwords_score": 2.0},
        "tts": {"model_dir": "models/sherpa/tts", "speaker_id": 0,
                "speed": 1.0, "num_threads": 2},
    },
    "wake": {"words": ["hey bota"],
             "command_timeout": 6.0,
             "followup_timeout": 8.0, "wake_ack": "在的",
             "ack_mode": "chirp",       # chirp=滴声(最快) / voice=说"在的" / both / none
             "chirp_freq": 880, "chirp_ms": 120},
    "mic": {"device_index": None},
    # 上下文轮数（多轮对话记忆，按 user/assistant 轮计；0=每句独立）
    "history_rounds": 4,
    # 手动触发对话开始（等价于 KWS 唤醒）：
    #   keyboard=终端按回车；http=POST/GET http://<host>:<port>/trigger
    #   香橙派物理按钮可接 GPIO 守护进程 curl 一下，或手机/浏览器开主页点按钮
    "trigger": {"keyboard": True, "http": True, "host": "0.0.0.0", "port": 8101},
}


def _merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def load_config(path: Optional[str]) -> dict:
    import copy
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        _merge(cfg, user)
    return cfg


# ==================== 手动触发通道（键盘回车 / HTTP / 外部程序）====================

class TriggerBus:
    """跨线程唤醒信号：任意来源 fire()，音频回调每帧 consume() 一次。"""

    def __init__(self):
        self._evt = threading.Event()
        self._source = ""

    def fire(self, source: str = "manual") -> None:
        self._source = source
        self._evt.set()

    def consume(self) -> Optional[str]:
        if self._evt.is_set():
            self._evt.clear()
            return self._source
        return None


class TriggerHTTPServer:
    """标准库 HTTP 触发服务（零额外依赖）。

    GET  /            聊天式实时控制台（唤醒按钮 + 文本输入 + 对话实况）
    GET  /state       当前状态 JSON（状态机 + 网关/LLM 摘要）
    GET/POST /trigger 触发一次语音监听（curl/物理按钮/网页均可）
    POST /say         直接下发文本指令（JSON: {"text": "..."}，绕过麦克风直接对话）
    GET  /say?text=.. 同上，GET 形式（方便纯 curl/无 body 的 IoT 设备）
    GET  /events      SSE 对话实况流（state/partial/user/assistant/tool/system）
    """

    def __init__(self, host: str, port: int, bus: TriggerBus, get_state, submit_text,
                 on_wake=None, event_bus: Optional[EventBus] = None,
                 info=None):
        import http.server

        bus_ref, state_ref, say_ref = bus, get_state, submit_text
        wake_ref = on_wake    # 同步回调：(source) -> None；缺省退回 bus.fire()
        events_ref = event_bus
        info_ref = info       # 无参回调：返回控制台展示的附加摘要 dict

        class _Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass  # 静默，不污染对话日志

            def _json(self, code: int, obj: dict):
                body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _fire(self):
                who = self.headers.get("X-Trigger-Source", "http")
                if wake_ref is not None:
                    wake_ref(who)
                else:
                    bus_ref.fire(who)
                self._json(200, {"ok": True, "state": state_ref()})

            def _say(self, text: str, who: str):
                text = (text or "").strip()
                if not text:
                    self._json(400, {"ok": False, "error": "text 不能为空"})
                    return
                say_ref(text, who)
                self._json(200, {"ok": True, "text": text, "state": state_ref()})

            def _events(self):
                if events_ref is None:
                    self._json(503, {"ok": False, "error": "事件总线不可用"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("X-Accel-Buffering", "no")
                self.send_header("Connection", "keep-alive")
                self.end_headers()
                q, history = events_ref.subscribe()
                try:
                    self._send_event({"type": "hello", "state": state_ref(),
                                      "history": history,
                                      "info": (info_ref() if info_ref else {})})
                    while True:
                        try:
                            self._send_event(q.get(timeout=15))
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")   # 心跳，防代理/超时掐断
                            self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                finally:
                    events_ref.unsubscribe(q)

            def _send_event(self, event: dict):
                data = json.dumps(event, ensure_ascii=False)
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()

            def do_POST(self):
                path = urllib_parse(self.path)
                if path == "/trigger":
                    self._fire()
                elif path == "/say":
                    try:
                        length = int(self.headers.get("Content-Length") or 0)
                        raw = self.rfile.read(length) if length else b"{}"
                        data = json.loads(raw.decode("utf-8") or "{}")
                        text = data.get("text", "") if isinstance(data, dict) else ""
                    except Exception:
                        text = ""
                    who = self.headers.get("X-Trigger-Source", "http")
                    self._say(text, who)
                else:
                    self._json(404, {"ok": False})

            def do_GET(self):
                from urllib.parse import urlparse, parse_qs
                u = urlparse(self.path)
                path, q = u.path, parse_qs(u.query)
                if path == "/trigger":
                    self._fire()
                elif path == "/say":
                    who = self.headers.get("X-Trigger-Source", "http")
                    self._say((q.get("text") or [""])[0], who)
                elif path == "/state":
                    self._json(200, {"state": state_ref()})
                elif path == "/events":
                    self._events()
                elif path == "/":
                    body = _CONSOLE_PAGE.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._json(404, {"ok": False})

        def urllib_parse(path: str) -> str:
            from urllib.parse import urlparse
            return urlparse(path).path

        self.httpd = http.server.ThreadingHTTPServer((host, port), _Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever,
                                       daemon=True, name="trigger-http")
        self.thread.start()
        self.host, self.port = host, self.httpd.server_address[1]

    def shutdown(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


# ---- 聊天式实时控制台（:8101/）----
_CONSOLE_PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hey Bota · 语音控制台</title>
<style>
:root{--bg:#0e1116;--panel:#161b23;--line:#232b38;--txt:#e8ebf0;--dim:#8b95a7;
--blue:#3b82f6;--green:#22c55e;--amber:#f59e0b;--red:#ef4444}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;flex-direction:column;background:var(--bg);
color:var(--txt);font-family:system-ui,"PingFang SC","Microsoft YaHei",sans-serif}
header{display:flex;align-items:center;gap:10px;padding:12px 18px;
border-bottom:1px solid var(--line);background:var(--panel)}
header .logo{font-weight:700;font-size:17px}
.pill{font-size:12px;padding:3px 10px;border-radius:99px;border:1px solid var(--line);
color:var(--dim);white-space:nowrap}
.pill b{color:var(--txt);font-weight:600}
.dot{width:9px;height:9px;border-radius:50%;background:var(--dim);display:inline-block;
margin-right:6px;vertical-align:1px}
main{flex:1;overflow-y:auto;padding:18px;display:flex;flex-direction:column;gap:10px}
.msg{max-width:min(720px,88%);padding:9px 13px;border-radius:14px;line-height:1.55;
font-size:15px;white-space:pre-wrap;word-break:break-word;animation:in .18s ease}
@keyframes in{from{opacity:0;transform:translateY(5px)}to{opacity:1}}
.user{align-self:flex-end;background:var(--blue);color:#fff;border-bottom-right-radius:4px}
.bot{align-self:flex-start;background:var(--panel);border:1px solid var(--line);
border-bottom-left-radius:4px}
.sys{align-self:center;color:var(--dim);font-size:12.5px}
.tool{align-self:flex-start;font-size:12.5px;color:var(--dim);background:none;
border-left:2px solid var(--line);border-radius:0;padding:2px 10px;max-width:92%;
font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap}
.tool.ok{border-color:var(--green)} .tool.err{border-color:var(--red)}
.partial{align-self:flex-start;color:var(--dim);font-style:italic;font-size:14px;
padding:0 4px;min-height:0}
footer{display:flex;gap:10px;padding:14px 18px;border-top:1px solid var(--line);
background:var(--panel)}
#mic{flex:0 0 auto;width:46px;height:46px;border-radius:50%;border:0;cursor:pointer;
background:linear-gradient(145deg,var(--blue),#1d4ed8);color:#fff;font-size:19px}
#mic:active{transform:scale(.94)} #mic.hot{animation:pulse 1.2s infinite}
@keyframes pulse{0%,100%{box-shadow:0 0 0 0 #3b82f655}50%{box-shadow:0 0 0 12px #3b82f600}}
#txt{flex:1;font-size:15px;padding:11px 14px;border-radius:12px;
border:1px solid var(--line);background:var(--bg);color:var(--txt);outline:none}
#txt:focus{border-color:var(--blue)}
#send{flex:0 0 auto;padding:0 22px;border-radius:12px;border:1px solid var(--line);
background:var(--panel);color:var(--txt);font-size:15px;cursor:pointer}
</style></head><body>
<header><span class="logo">Hey Bota</span>
<span class="pill"><span class="dot" id="dot"></span><b id="st">连接中…</b></span>
<span class="pill">网关 <b id="gw">--</b></span>
<span class="pill">LLM <b id="llm">--</b></span>
</header>
<main id="log"><div class="partial" id="partial"></div></main>
<footer><button id="mic" title="唤醒并开始聆听" onclick="wake()">🎤</button>
<input id="txt" placeholder="或直接输入文字指令，回车发送"
 onkeydown="if(event.key==='Enter')say()">
<button id="send" onclick="say()">发送</button></footer>
<script>
const ST={IDLE:['待唤醒','var(--dim)'],COMMAND:['聆听指令','var(--blue)'],
THINKING:['思考中','var(--amber)'],FOLLOWUP:['可追问','var(--green)']};
const log=document.getElementById('log'),partial=document.getElementById('partial');
let curBot=null;
function setState(s){const m=ST[s]||[s||'离线','var(--red)'];
 document.getElementById('st').textContent=m[0];
 document.getElementById('dot').style.background=m[1];
 document.getElementById('mic').className=(s==='COMMAND'?'hot':'');}
function add(cls,text){const d=document.createElement('div');d.className=cls;
 d.textContent=text;log.insertBefore(d,partial);log.scrollTop=log.scrollHeight;
 return d;}
function setPartial(t){partial.textContent=t;t?partial.style.display='':partial.style.display='none';}
function handle(e){
 if(e.type==='hello'){setState(e.state);
   if(e.info){document.getElementById('gw').textContent=e.info.gateway||'--';
              document.getElementById('llm').textContent=e.info.llm||'--';}
   for(const h of (e.history||[]))render(h);return;}
 if(e.type==='state'){setState(e.state);return;}
 render(e);}
function render(e){switch(e.type){
 case 'partial':setPartial(e.text);break;
 case 'user':setPartial('');curBot=null;add('user',e.text);break;
 case 'delta':if(!curBot){setPartial('');curBot=add('bot','');}
   curBot.textContent+=e.text;log.scrollTop=log.scrollHeight;break;
 case 'turn_end':curBot=null;break;
 case 'tool':add('tool '+(e.ok?'ok':'err'),
   (e.ok?'✓ ':'✗ ')+e.name+' '+JSON.stringify(e.arguments||{})+
   (e.result?'\\n   → '+e.result:''));break;
 case 'system':add('sys',e.text);break;}}</script>
<script>
async function wake(){try{await fetch('/trigger')}catch(e){}}
async function say(){const el=document.getElementById('txt');const v=el.value.trim();
 if(!v)return;el.value='';
 try{await fetch('/say',{method:'POST',headers:{'Content-Type':'application/json'},
 body:JSON.stringify({text:v})});}catch(e){add('sys','发送失败：'+e);}}
let es;function connect(){es=new EventSource('/events');
 es.onmessage=m=>{try{handle(JSON.parse(m.data))}catch(e){}};
 es.onerror=()=>{setState('');document.getElementById('st').textContent='重连中…';};}
connect();</script></body></html>"""


# ==================== 通用 OpenAI 兼容 LLM 客户端（流式 + 工具调用）====================

_QUANT_TAIL = re.compile(
    r"-(q2_k|q3_k_[sml]|q4_0|q4_k_[ms]|q5_0|q5_k_[ms]|q6_k|q8_0|fp16|f16)$")


def resolve_llm(cfg: dict) -> tuple[str, str]:
    """按 mode 解析出 (base_url, model)；云端模式自动纠正端点与模型名。

    mode 在 CLOUD_LLM_BASES 里（siliconflow / dashscope）即云端 OpenAI 兼容端点：
    base_url 还指着 127.0.0.1（本地服务的残留）就换回该模式的官方端点，模型名去掉
    GGUF 量化后缀（"qwen2.5-3b-instruct-q4_k_m" → "qwen2.5-3b-instruct"）。
    硅基流动的模型名带组织前缀（"Qwen/Qwen3.5-4B"），不含量化后缀，原样透传。
    """
    mode = cfg["llm"]["mode"]
    base = cfg["llm"]["base_url"].rstrip("/")
    model = cfg["llm"]["model"]
    cloud_base = CLOUD_LLM_BASES.get(mode)
    if cloud_base:
        if not base or "127.0.0.1" in base or "localhost" in base:
            base = cloud_base.rstrip("/")   # mode 已切云端但 base_url 忘改：自动纠正
        model = _QUANT_TAIL.sub("", model)
    return base, model


# 云端模式的默认附加请求体参数（直接合并进每次 /chat/completions 请求）。
# Qwen3.5 是「思考型」模型：默认先把 reasoning_content 流完才吐正文，实测语音场景首字
# 20~60s，等于不可用；硅基流动认顶层 enable_thinking=false（实测首字 ~1s），
# 而 chat_template_kwargs 这类 vLLM 写法它不认，别照搬。
CLOUD_LLM_EXTRA_BODY = {
    "siliconflow": {"enable_thinking": False},
}


def resolve_extra_body(cfg: dict) -> dict:
    """该 mode 要合并进请求体的额外参数：模式默认值 + config llm.extra_body 覆盖。"""
    body = copy.deepcopy(CLOUD_LLM_EXTRA_BODY.get(cfg["llm"]["mode"], {}))
    custom = cfg["llm"].get("extra_body")
    if custom:
        _merge(body, custom)
    return body


# 远程 LLM API Key 文件候选（按顺序取第一个存在且含非注释行的）。llm_key.txt 为通用名
# （跟 mode 无关，推荐）；siliconflow_key.txt / dashscope_key.txt 为按服务商分的名字。
# 三者都已 gitignore + dockerignore，绝不入库/入镜像。
LLM_KEY_FILE_CANDIDATES = ("llm_key.txt", "siliconflow_key.txt", "dashscope_key.txt")

# 远程 Key 的环境变量候选：通用名优先，再按服务商分。
LLM_KEY_ENV_VARS = ("LLM_API_KEY", "SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY")


def _read_key_file(cfg: dict) -> Optional[str]:
    """从密钥文件读第一行非注释内容作为远程 LLM API Key。

    优先读 cfg["llm"]["api_key_file"]（相对 PC_Test 或绝对路径），再回落到
    llm_key.txt / siliconflow_key.txt / dashscope_key.txt。找不到返回 None。
    """
    cands: list[str] = []
    custom = (cfg.get("llm") or {}).get("api_key_file")
    if custom:
        cands.append(custom if os.path.isabs(custom)
                     else os.path.join(PC_TEST_DIR, custom))
    cands += [os.path.join(PC_TEST_DIR, f) for f in LLM_KEY_FILE_CANDIDATES]
    for path in cands:
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    for line in f:
                        s = line.strip()
                        if s and not s.startswith("#"):
                            return s
        except OSError:
            continue
    return None


def resolve_api_key(cfg: dict) -> Optional[str]:
    """远程 LLM API Key 的单一取用点，优先级从高到低：

      1. config ``llm.api_key``（``main`` 已把 --api-key / SMART_HOME_LLM_API_KEY 并入此处）
      2. 环境变量 LLM_API_KEY / SILICONFLOW_API_KEY / DASHSCOPE_API_KEY
      3. 密钥文件 llm_key.txt / siliconflow_key.txt / dashscope_key.txt
         （或 llm.api_key_file 指定）

    这样「把 Key 放进文件」在直接 ``python voice_assistant.py``、start_voice、
    --test-llm / --self-check 与 Docker 里都一致生效，而不再只依赖 PowerShell 启动器。
    """
    key = cfg["llm"].get("api_key")
    if key and key != "none":
        return key
    for var in LLM_KEY_ENV_VARS:
        env = os.environ.get(var)
        if env:
            return env
    return _read_key_file(cfg)


RETRY_BACKOFF_S = 0.8


def _should_retry(err: Exception, attempt: int,
                  content_parts: list, tc_acc: dict) -> bool:
    """这次失败值不值得立刻再发一次。

    只重试「一个字节都还没吐」的 5xx/429/超时/连接失败：半句内容已经喂给 TTS 播出去了，
    重来会让用户听见两句拼在一起。401/400 这类是配置错误，重试没有意义。
    """
    if attempt != 1 or content_parts or tc_acc:
        return False
    s = str(err)
    return ("超时" in s or "连接失败" in s
            or any(f"HTTP {code}" in s for code in (408, 425, 429, 500, 502, 503, 504)))


async def stream_chat(base_url: str, api_key: Optional[str], model: str,
                      messages: list, tools: Optional[list] = None,
                      on_content=None, extra_body: Optional[dict] = None,
                      timeout_s: float = LLM_TIMEOUT_S) -> tuple[str, list]:
    """流式调用 OpenAI 兼容 /chat/completions。

    on_content(token) 在每个内容 token 到达时回调（喂 TTS 用）。
    extra_body 里的键直接合并进请求体（如 enable_thinking / max_tokens）。
    timeout_s 是「两段数据之间」的最大间隔，超时会抛 RuntimeError。
    返回 (完整content, tool_calls列表)。
    """
    import httpx
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key and api_key != "none":
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"model": model, "messages": messages, "stream": True}
    if tools:
        payload["tools"] = tools
    if extra_body:
        payload.update(extra_body)
    content_parts, tc_acc = [], {}
    # 必须给读超时：云端偶尔接下连接却一个字节都不发，timeout=None 会让这一轮永远
    # 卡在 THINKING，麦克风/键盘通道跟着一起死（实测硅基流动会 503 或长时间静默）。
    timeout = httpx.Timeout(connect=8.0, read=timeout_s, write=15.0, pool=8.0)
    # 免费档常被挤到 503/静默，实测同一请求紧接着重试就能通。只重试「一个字节都还没
    # 吐」的情况——半句已经喂给 TTS 播出去了，重来会让用户听见两句拼接。
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code != 200:
                        body = (await resp.aread()).decode("utf-8", "replace")[:300]
                        raise RuntimeError(f"LLM HTTP {resp.status_code}: {body}")
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {}) or {}
                        c = delta.get("content")
                        if c:
                            content_parts.append(c)
                            if on_content:
                                on_content(c)
                        tcs = delta.get("tool_calls")
                        if tcs:
                            for tc in tcs:
                                idx = tc.get("index", 0)
                                slot = tc_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                                if tc.get("id"):
                                    slot["id"] = tc["id"]
                                fn = tc.get("function", {}) or {}
                                if fn.get("name"):
                                    slot["name"] = fn["name"]
                                if fn.get("arguments"):
                                    slot["arguments"] += fn["arguments"]
            break
        except httpx.TimeoutException as e:
            err = RuntimeError(
                f"LLM 超时：{timeout_s:.0f}s 内没有响应数据（{base_url}）；"
                "服务商抖动稍后重说即可，长期如此可调大 llm.timeout_s")
            if not _should_retry(err, attempt, content_parts, tc_acc):
                raise err from e
            print(f"[LLM] {err} —— 立即重试一次", flush=True)
            await asyncio.sleep(RETRY_BACKOFF_S)
        except (httpx.TransportError, OSError) as e:
            err = RuntimeError(f"LLM 连接失败：{type(e).__name__}: {e}")
            if not _should_retry(err, attempt, content_parts, tc_acc):
                raise err from e
            print(f"[LLM] {err} —— 立即重试一次", flush=True)
            await asyncio.sleep(RETRY_BACKOFF_S)
        except RuntimeError as e:
            if not _should_retry(e, attempt, content_parts, tc_acc):
                raise
            print(f"[LLM] {e} —— 立即重试一次", flush=True)
            await asyncio.sleep(RETRY_BACKOFF_S)
    tool_calls = [{
        "id": v["id"] or f"call_{i}",
        "type": "function",
        "function": {"name": v["name"], "arguments": v["arguments"]},
    } for i, v in tc_acc.items()]
    return "".join(content_parts), tool_calls


# ==================== 语音助手主体 ====================

class VoiceAssistant:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.gateway = HardwareGateway(cfg["gateway"]["url"])
        self.llm_mode = cfg["llm"]["mode"]
        self.llm_base_url, self.llm_model = resolve_llm(cfg)
        self.llm_api_key = resolve_api_key(cfg)
        self.llm_extra_body = resolve_extra_body(cfg)
        self.llm_timeout_s = float(cfg["llm"].get("timeout_s") or LLM_TIMEOUT_S)
        self.system_prompt = cfg["llm"]["system_prompt"]
        self.history_rounds = int(cfg.get("history_rounds", 4))
        from tts_player import TtsPlayer  # 惰性导入（依赖 sounddevice）
        self.tts = TtsPlayer(cfg=cfg["sherpa"]["tts"])
        self.wake_words = cfg["wake"]["words"]
        self.command_timeout = cfg["wake"]["command_timeout"]
        self.followup_timeout = cfg["wake"].get("followup_timeout", 8.0)
        self.wake_ack = cfg["wake"]["wake_ack"]
        self.ack_mode = cfg["wake"].get("ack_mode", "chirp")
        self.chirp_freq = int(cfg["wake"].get("chirp_freq", 880))
        self.chirp_ms = int(cfg["wake"].get("chirp_ms", 120))
        self._last_state = None         # 状态变化时才打印/广播，避免刷屏
        self.mic_device = cfg["mic"]["device_index"]

        self.trigger = TriggerBus()     # 手动触发（键盘/HTTP/外部程序）
        self.trigger_http = None
        self.events = EventBus()        # SSE 对话实况

        self.listener = None            # sherpa_listener.SherpaListener
        self.stream = None
        self.state = "IDLE"
        self.command_state_start = 0.0
        self.command_queue: "queue.Queue[str]" = queue.Queue()

        self.llm_tools: list = []       # 网关工具 schema（run() 启动时拉取）
        self.history: list = []         # 多轮上下文（仅 user/assistant 文本）

    # ── 事件广播 ──
    def publish(self, etype: str, **fields) -> None:
        self.events.publish(etype, **fields)

    # ── Sherpa-ONNX + 麦克风 ──
    def load_listener(self):
        from sherpa_listener import SherpaListener, check_models
        missing = check_models(self.cfg)
        if missing:
            raise FileNotFoundError(
                "Sherpa-ONNX 模型缺失: " + ", ".join(missing) +
                "\n  请先运行: py -3.13 download_sherpa_models.py")
        self.listener = SherpaListener(self.cfg)

    def _start_mic(self):
        if os.environ.get("SMART_HOME_DISABLE_MIC") == "1":
            # 无麦克风的部署（纯硬件网关 / 容器测试）：跳过音频采集，
            # HTTP /say 文本对话与硬件网关调用仍正常工作。
            print("[语音] SMART_HOME_DISABLE_MIC=1，已跳过麦克风初始化", flush=True)
            return
        import sounddevice as sd
        self.stream = sd.InputStream(
            samplerate=16000, channels=1, dtype="float32",
            blocksize=1600, device=self.mic_device,  # 100ms/帧，KWS/ASR 低延迟
            callback=self._audio_callback)
        self.stream.start()

    def _manual_wake(self, who: str = "http") -> None:
        """外部（HTTP / 面板按钮 / 自动化按键）触发的唤醒。

        麦克风在跑时走 TriggerBus，由音频回调在下一帧消费（低延迟、线程安全）；
        麦克风被禁用（SMART_HOME_DISABLE_MIC）时没有音频循环来消费，
        直接切状态机——保证「跳过唤醒词」这条链路在无声卡部署下依然生效。
        """
        if self.stream is not None:
            self.trigger.fire(who)
        else:
            self._on_wake(who, time.time(), manual=True)
            # 没有音频回调来兜底超时，自己起个定时器把状态收回 IDLE，
            # 否则面板会一直显示「聆听指令中」
            threading.Timer(self.command_timeout, self._idle_if_command).start()

    def _idle_if_command(self):
        """无麦克风部署下 COMMAND 状态的超时回收（音频回调不在时使用）。"""
        if self.state == "COMMAND":
            self._set_state("IDLE", note="未收到指令，回到待唤醒状态")

    def _set_state(self, new_state: str, note: str = ""):
        self.state = new_state
        self._emit_state(new_state)
        if note:
            self.publish("system", text=note)

    def _emit_state(self, new_state):
        """状态变化时打印醒目状态行并广播给 SSE 控制台。"""
        if new_state == self._last_state:
            return
        self._last_state = new_state
        self.publish("state", state=new_state)
        if new_state == "IDLE":
            print("\n  [⏸ 待唤醒] 说「Hey Bota」唤醒我（也可直接打字）", flush=True)
        elif new_state == "COMMAND":
            print(f"\n  [🎤 请说指令] （{self.command_timeout:.0f}s 内有效）", flush=True)
        elif new_state == "THINKING":
            print("\n  [🤖 思考中] 正在调用大模型...", flush=True)
        elif new_state == "FOLLOWUP":
            print(f"\n  [💬 追问中] {self.followup_timeout:.0f}s 内可直接说下一句", flush=True)

    def _ack(self):
        """唤醒反馈：chirp 滴声零延迟 / voice 说「在的」/ both / none。"""
        if self.ack_mode in ("chirp", "both"):
            self.tts.chirp(self.chirp_freq, self.chirp_ms)
        if self.ack_mode in ("voice", "both") and self.wake_ack:
            self.tts.speak(self.wake_ack)

    def _on_wake(self, keyword: str, now: float, manual: bool = False):
        # 手动触发可打断正在播放的回答（barge-in）；语音唤醒受回声抑制约束不会走到这里
        if manual and self.tts.is_busy():
            self.tts.stop()
            print("\n  [✋ 打断] 已停止当前播报", flush=True)
            self.publish("system", text="已打断当前播报")
        self.state = "COMMAND"
        self.command_state_start = now
        if manual and self.listener:
            self.listener.reset_asr()   # 手动触发：丢弃触发前录入的半句噪声
        self._ack()
        tag = "手动触发" if manual else "KWS 命中"
        print(f"\n  [⭐ 唤醒成功！] {tag}「{keyword}」→ 已切换到指令模式", flush=True)
        self.publish("system", text=f"唤醒成功（{tag}）")
        self._emit_state("COMMAND")

    def submit_text(self, text: str, source: str = "键盘") -> None:
        """键盘/HTTP 直接输入文本指令（绕过 ASR）：打断播报、清空残句、入队对话。"""
        text = (text or "").strip()
        if not text:
            return
        if self.tts.is_busy():
            self.tts.stop()
        print(f"\n  [📥 {source}文本指令] {text}", flush=True)
        self.publish("user", text=text, source=source)
        self.state = "THINKING"
        self._last_state = "THINKING"  # 抑制随后重复的思考状态行
        self.publish("state", state="THINKING")
        if self.listener:
            self.listener.reset_asr()
        self.command_queue.put(text)

    def _on_final(self, text: str):
        print(f"  [识别] {text}", flush=True)
        if self.state == "COMMAND":
            cmd = self._strip_wake_prefix(text)
            if cmd:
                self.command_queue.put(cmd)
                print(f"  [✅ 指令已收到] {cmd}  → 交给大模型处理", flush=True)
                self.publish("user", text=cmd, source="语音")
                self._set_state("THINKING")
            else:
                # 只有唤醒词、没说指令：留在 COMMAND 等下一句
                print("  [💬] 只听到唤醒词，继续听指令...", flush=True)
        elif self.state == "FOLLOWUP":
            # 追问模式：无需唤醒词，直接当指令
            self.command_queue.put(text)
            print(f"  [✅ 追问] {text}  → 交给大模型处理", flush=True)
            self.publish("user", text=text, source="语音·追问")
            self._set_state("THINKING")

    @staticmethod
    def _norm_wake(t: str) -> str:
        """归一化：小写 + 去空格/标点（兼容 "Hey Bota," / "heybota" / "hey  bota"）。"""
        return re.sub(r"[\s,，。.!！?？、]+", "", t.strip().lower())

    def _strip_wake_prefix(self, text: str) -> str:
        """KWS 唤醒后用户可能「唤醒词+指令」一口气说完，ASR 文本含唤醒词，剥掉前缀。

        原文的空格/标点数量不可控（"Hey Bota,开灯"/"heybota 开灯"），
        按归一化后应消费的字符数在原文上扫描，跳过空白标点。
        """
        t = text.strip()
        norm_t = self._norm_wake(t)
        for w in self.wake_words:
            nw = self._norm_wake(w)
            if not nw or not norm_t.startswith(nw):
                continue
            i, consumed = 0, 0
            while i < len(t) and consumed < len(nw):
                if not re.fullmatch(r"[\s,，。.!！?？、]", t[i]):
                    consumed += 1
                i += 1
            return t[i:].strip(" ，,.。!！?？、")
        return t

    def _audio_callback(self, indata, frames, time_info, status):
        try:
            import numpy as np
            samples = np.frombuffer(indata, dtype=np.float32) \
                if isinstance(indata, (bytes, bytearray)) else indata[:, 0]
            now = time.time()
            # 手动触发（键盘/HTTP/外部程序）：必须在 accept 之前处理，
            # reset 掉旧 ASR 半句，避免触发前的残句同帧被当成指令提交
            manual_src = self.trigger.consume()
            if manual_src:
                self._on_wake(manual_src, now, manual=True)
            events = self.listener.accept(samples)
            tts_busy = self.tts.is_busy()
            for kind, text in events:
                if kind == "wake":
                    # 回声抑制：TTS 播放时忽略 KWS 命中（防止听到自己声音自唤醒）
                    if not tts_busy:
                        self._on_wake(text, now)
                elif kind == "partial":
                    self._emit_partial(text)
                elif kind == "final":
                    self._on_final(text)
            # 超时检查（由音频帧驱动）
            if self.state == "COMMAND" and now - self.command_state_start > self.command_timeout:
                self._set_state("IDLE", note="未收到指令，回到待唤醒状态")
            elif self.state == "FOLLOWUP" and now - self.command_state_start > self.followup_timeout:
                self._set_state("IDLE")
        except Exception as e:
            print(f"\n[音频] 回调异常: {e}", flush=True)

    _partial_shown = ""

    def _emit_partial(self, text: str):
        """ASR 部分识别：终端行内刷新 + SSE 广播（内容没变不重发）。"""
        if text == self._partial_shown:
            return
        self._partial_shown = text
        shown = text if len(text) <= 30 else text[-30:]
        print(f"  [听到] {shown}", end="\r", flush=True)
        self.publish("partial", text=shown)

    # ── LLM 流式 + 工具调用（经 web 硬件网关执行）──
    async def stream_llm(self, messages, tools):
        """流式调用 LLM，token 边生成边喂 TTS/广播；返回 (content, tool_calls)。"""
        def on_token(tok):
            self.tts.feed_token(tok)
            self.publish("delta", text=tok)

        try:
            content, tool_calls = await stream_chat(
                self.llm_base_url, self.llm_api_key, self.llm_model,
                messages, tools, on_content=on_token, extra_body=self.llm_extra_body,
                timeout_s=self.llm_timeout_s)
            return content, tool_calls
        except Exception as e:
            print(f"[LLM] 调用失败: {e}", flush=True)
            self.publish("system", text=f"大模型调用失败: {e}")
            self.tts.speak("大模型出错了")
            return "", []

    def _context_messages(self, user_text: str) -> list:
        """system + 最近 history_rounds 轮 + 本句用户输入。"""
        messages = [{"role": "system", "content": self.system_prompt}]
        tail = self.history[-2 * max(0, self.history_rounds):] \
            if self.history_rounds > 0 else []
        messages.extend(tail)
        messages.append({"role": "user", "content": user_text})
        return messages

    def _remember(self, user_text: str, answer: str) -> None:
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": answer})
        cap = 2 * max(1, self.history_rounds)
        if len(self.history) > cap:
            del self.history[:-cap]

    async def handle_command(self, user_text):
        print(f"[你] {user_text}", flush=True)
        messages = self._context_messages(user_text)
        final_content = ""
        for rnd in range(3):
            content, tool_calls = await self.stream_llm(messages, self.llm_tools)
            if content:
                final_content = content
                print(f"[助手] {content}", flush=True)   # 输出大模型的文字回答
            if not tool_calls:
                break
            messages.append({
                "role": "assistant",
                "content": content or "",
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                name = tc["function"]["name"]
                raw_args = tc["function"]["arguments"] or "{}"
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError as e:
                    messages.append({"role": "tool", "tool_call_id": tc["id"],
                                     "content": f"error: 参数解析失败 {e}"})
                    continue
                print(f"[工具] 调用 {name}({args})", flush=True)
                ok, result_text = await asyncio.to_thread(
                    self.gateway.call, name, args)
                if not ok and not result_text.startswith("error"):
                    result_text = f"error: {result_text}"
                print(f"[工具] {name} -> {result_text}", flush=True)
                self.publish("tool", name=name, arguments=args,
                             ok=ok, result=result_text[:300])
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": result_text})
        self.tts.flush()
        self.publish("turn_end")
        # 若本轮只有工具调用没有解说词，最后再请求一次大模型生成自然语言总结
        if final_content == "" and any(m.get("role") == "tool" for m in messages):
            content, _ = await self.stream_llm(messages, self.llm_tools)
            if content:
                final_content = content
                print(f"[助手] {content}", flush=True)
            self.publish("turn_end")
        self._remember(user_text, final_content or "（已执行）")
        if not final_content:
            print("[助手] (无文字回复)", flush=True)
        await asyncio.sleep(0.2)

    # ── 主循环 ──
    async def run(self):
        loop = asyncio.get_running_loop()

        # 工具 schema 来自 web 硬件网关；web 可能还在启动（start_all/compose 同起），
        # 指数退避直到拿通为止——拿不通不影响文本对话，只是硬件动作会失败。
        backoff = 2.0
        while not self.llm_tools:
            try:
                self.llm_tools = await asyncio.to_thread(self.gateway.fetch_tools)
            except Exception as e:
                print(f"[网关] 工具列表获取失败（{self.gateway.base_url}）: {e}"
                      f"（{backoff:.0f}s 后重试；run_web.py 需要先起来）", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
        print(f"[网关] 已加载 {len(self.llm_tools)} 个硬件工具: "
              f"{[t['function']['name'] for t in self.llm_tools]}", flush=True)

        # 输入通道（配置可关）：键盘（打字对话/空行触发）+ HTTP（/trigger、/say）
        tcfg = self.cfg.get("trigger", {})
        if tcfg.get("keyboard", True):
            _start_keyboard_console(self)
        if tcfg.get("http", True):
            try:
                self.trigger_http = TriggerHTTPServer(
                    tcfg.get("host", "0.0.0.0"),
                    int(tcfg.get("port", 8101)),
                    self.trigger, lambda: self.state,
                    lambda text, who: self.submit_text(text, source=who),
                    on_wake=self._manual_wake,
                    event_bus=self.events,
                    info=self._console_info)
            except Exception as e:
                print(f"[触发] HTTP 接口启动失败（不影响语音）: {e}", flush=True)

        self._start_mic()
        print("=" * 56, flush=True)
        print("  🎤 语音助手已启动（Sherpa-ONNX 前端 + 云端 LLM）", flush=True)
        print("  麦克风: " + (f"索引 {self.mic_device}" if self.mic_device is not None else "系统默认"), flush=True)
        print("  唤醒词(KWS): " + " / ".join(self.listener.keywords), flush=True)
        print(f"  LLM: {self.llm_mode} · {self.llm_model} @ {self.llm_base_url}", flush=True)
        print(f"  硬件网关: {self.gateway.base_url}（{len(self.llm_tools)} 工具）", flush=True)
        if tcfg.get("keyboard", True):
            print("  ⌨️  键盘对话: 直接打字回车发送指令；空回车=开始语音监听", flush=True)
        if self.trigger_http is not None:
            p = self.trigger_http.port
            print(f"  🌐 控制台: http://<本机IP>:{p}/ （聊天实况）", flush=True)
            print(f"         语音触发 POST/GET /trigger；文本指令 POST /say；实况流 GET /events",
                  flush=True)
        print("=" * 56, flush=True)
        self._emit_state("IDLE")
        try:
            while True:
                text = await loop.run_in_executor(None, self.command_queue.get)
                if text is None:
                    break
                try:
                    await self.handle_command(text)
                except Exception as e:
                    print(f"[错误] 处理指令失败: {e}", flush=True)
                    self.publish("system", text=f"处理指令失败: {e}")
                    self.tts.speak("出错了，请重说")
                finally:
                    # 处理完毕，进入追问模式（followup_timeout 内可直接说话，无需重新唤醒）
                    self.command_state_start = time.time()
                    if self.listener:
                        self.listener.reset_asr()  # 清掉思考期间误录的半句
                    print(f"\n  [💬 可追问] {self.followup_timeout:.0f}s 内可直接说下一句，超时回到待唤醒", flush=True)
                    self._set_state("FOLLOWUP")
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        try:
            if self.stream is not None:
                self.stream.stop()
        except Exception:
            pass
        if self.trigger_http is not None:
            self.trigger_http.shutdown()
        self.tts.shutdown()

    def _console_info(self) -> dict:
        """控制台页的状态摘要（hello 事件携带）。"""
        ok, info = self.gateway.health()
        gw = "在线" if ok and info.get("online") else ("可达" if ok else "离线")
        return {"gateway": f"{gw} @ {self.gateway.base_url}",
                "llm": f"{self.llm_mode} · {self.llm_model}"}


# ==================== 手动触发键盘通道 ====================

def _start_keyboard_console(assistant: "VoiceAssistant") -> None:
    """终端键盘双通道（stdin 为 EOF/管道时静默禁用，避免空转误触发）：

        直接打字后回车 → 文本指令，绕过麦克风直接和大模型对话；
        只按回车（空行）→ 开启语音监听（等价喊唤醒词）。
    """
    def loop():
        try:
            while True:
                line = sys.stdin.readline()
                if line == "":
                    return  # EOF：后台运行/输入被重定向，键盘通道自动失效
                text = line.strip()
                if text:
                    assistant.submit_text(text, source="键盘")
                else:
                    assistant.trigger.fire("键盘回车")
        except Exception:
            return

    threading.Thread(target=loop, daemon=True, name="keyboard-console").start()


# ==================== 自检 / REPL 子命令 ====================

async def self_check(cfg: dict) -> int:
    print("=" * 60)
    print("  语音模式自检（Sherpa-ONNX + 硬件网关）")
    print("=" * 60)
    ok = True

    # (a) Sherpa 模型文件 + 引擎加载
    print("\n[a] Sherpa-ONNX 模型与引擎...", flush=True)
    try:
        from sherpa_listener import SherpaListener, check_models
        missing = check_models(cfg)
        if missing:
            raise FileNotFoundError(", ".join(missing))
        listener = SherpaListener(cfg)
        print(f"    OK: KWS/ASR 引擎加载成功，唤醒词: {listener.keywords}")
    except Exception as e:
        print(f"    FAIL: {e}")
        print("    → 运行: py -3.13 download_sherpa_models.py")
        ok = False

    # (b) TTS 引擎
    print("\n[b] TTS 引擎（VITS）...", flush=True)
    try:
        from tts_player import TtsPlayer
        t = TtsPlayer(cfg=cfg["sherpa"]["tts"])
        print(f"    OK: VITS 加载成功（采样率 {t.sample_rate}Hz）")
        t.shutdown()
    except Exception as e:
        print(f"    FAIL: {e}")
        ok = False

    # (c) 麦克风 1s 采样
    print("\n[c] 麦克风采样...", flush=True)
    if os.environ.get("SMART_HOME_DISABLE_MIC") == "1":
        print("    SKIP: SMART_HOME_DISABLE_MIC=1（无麦克风部署）")
    else:
        try:
            import sounddevice as sd
            sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                           device=cfg["mic"]["device_index"]).start()
            time.sleep(1.0)
            print("    OK: 麦克风可读")
        except Exception as e:
            print(f"    FAIL: {e}")
            ok = False

    # (d) LLM 引擎可达
    print("\n[d] LLM 引擎可达性...", flush=True)
    try:
        import httpx
        base, model = resolve_llm(cfg)
        mode = cfg["llm"]["mode"]
        headers = {}
        api_key = resolve_api_key(cfg)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{base}/models", headers=headers)
            ids = [m.get("id") for m in r.json().get("data", [])]
            if mode in CLOUD_LLM_BASES:
                if not api_key:
                    print(f"    FAIL: 未配置 API Key（{mode} 模式需要，"
                          "见 llm_key.txt / LLM_API_KEY / llm.api_key）")
                    ok = False
                elif model in ids or any(i and i.split("/")[-1] == model.split("/")[-1]
                                         for i in ids):
                    print(f"    OK: {mode} 端点可达，模型 {model}")
                else:
                    print(f"    提示: /models 列表未含 {model}（云端列表不全属正常，"
                          f"可直接 --test-llm 验证）")
            else:
                if model in ids:
                    print(f"    OK: 本地 Qwen 服务已加载 {model}")
                else:
                    print(f"    FAIL: 本地服务返回模型 {ids}，期望 {model}")
                    print("    → 先启动: py -3.13 qwen_server.py（或双击 start_voice.bat）")
                    ok = False
    except Exception as e:
        print(f"    FAIL: {e}")
        if cfg["llm"]["mode"] == "local":
            print("    → 本地模式先启动: py -3.13 qwen_server.py（模型未下载则先跑 download_qwen.py）")
        else:
            print("    → 云端模式需把 Key 写进 PC_Test/llm_key.txt（或设 LLM_API_KEY /"
                  " config llm.api_key）；端点不可达也可能是网络/代理问题")
        ok = False

    # (e) web 硬件网关
    print("\n[e] web 硬件网关（/api/hardware/tools）...", flush=True)
    gw = HardwareGateway(cfg["gateway"]["url"])
    try:
        tools = gw.fetch_tools()
        names = [t["function"]["name"] for t in tools]
        print(f"    OK: {len(names)} 个工具: {names}")
        if len(names) < 9:
            print("    警告: 期望 13 个工具（部分串口工具未注册？）")
    except Exception as e:
        print(f"    FAIL: {e}")
        print("    → 语音不再直连串口；请先启动 web 服务: py -3.13 run_web.py")
        ok = False
    else:
        alive, info = gw.health()
        if not alive:
            print(f"    警告: /api/status 不可达: {info.get('error')}")
        elif not info.get("online"):
            print(f"    警告: 硬件桥离线: {info.get('last_error') or '串口未连接'}"
                  "（web 是否 --no-serial 在跑？）")

    print("\n" + "=" * 60)
    print("  自检" + ("通过 ✓" if ok else "存在失败项 ✗（见上方提示）"))
    print("=" * 60)
    return 0 if ok else 1


def kws_repl(cfg: dict) -> int:
    """KWS + ASR 实时 REPL：说「Hey Bota」测唤醒，说话测识别（Ctrl+C 退出）。"""
    import sounddevice as sd
    from sherpa_listener import SherpaListener, check_models

    missing = check_models(cfg)
    if missing:
        print(f"模型缺失: {missing}\n  → py -3.13 download_sherpa_models.py")
        return 1
    listener = SherpaListener(cfg)

    def cb(indata, frames, time_info, status):
        samples = indata[:, 0]
        for kind, text in listener.accept(samples):
            if kind == "wake":
                print(f"  [⭐ KWS 唤醒] {text}", flush=True)
            elif kind == "partial":
                print(f"  [partial] {text}", end="\r", flush=True)
            elif kind == "final":
                print(f"  [FINAL] {text}", flush=True)

    print("[kws-repl] 说「Hey Bota」测试唤醒（中文模型用拼音近似，发音贴近「黑波塔」）；"
          "随便说话测识别（Ctrl+C 退出）", flush=True)
    with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                        blocksize=1600, device=cfg["mic"]["device_index"],
                        callback=cb):
        try:
            while True:
                time.sleep(0.2)
        except KeyboardInterrupt:
            print("\n退出。")
    return 0


async def test_llm(cfg: dict, text: str) -> int:
    """一次性验证 LLM 引擎：①普通对话流式输出 ②工具调用探测。"""
    base, model = resolve_llm(cfg)
    api_key = resolve_api_key(cfg)
    extra_body = resolve_extra_body(cfg)
    timeout_s = float(cfg["llm"].get("timeout_s") or LLM_TIMEOUT_S)
    print(f"[LLM] 模式={cfg['llm']['mode']}  模型={model}  端点={base}"
          f"  Key={'已配置' if api_key else '缺失'}")
    if extra_body:
        print(f"[LLM] 附加参数={json.dumps(extra_body, ensure_ascii=False)}")

    print(f"\n[测试1] 普通对话（流式输出）: {text}")
    try:
        t0 = time.monotonic()
        content, _ = await stream_chat(base, api_key, model,
                                       [{"role": "user", "content": text}],
                                       on_content=lambda t: print(t, end="", flush=True),
                                       extra_body=extra_body, timeout_s=timeout_s)
        print()
        if not content.strip():
            print("  FAIL: 无内容返回（若模型默认「思考」，正文会排在 reasoning_content 之后；"
                  "用 llm.extra_body 关思考或换 Instruct 模型）")
            return 1
        print(f"  OK: 流式回复正常（{time.monotonic() - t0:.2f}s）")
    except Exception as e:
        print(f"\n  FAIL: {e}")
        return 1

    print("\n[测试2] 工具调用探测（「把灯调成红色」应触发 light 工具）:")
    tool = {"type": "function", "function": {
        "name": "light",
        "description": "控制灯光：开关、颜色（on/off/red/green/blue）",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["on", "off", "red", "green", "blue"]}},
            "required": ["action"]}}}
    try:
        t0 = time.monotonic()
        content, tool_calls = await stream_chat(
            base, api_key, model,
            [{"role": "system", "content": "你是智能家居助手，必须用工具执行硬件操作，禁止只回复文字。"},
             {"role": "user", "content": "把灯调成红色"}],
            tools=[tool], extra_body=extra_body, timeout_s=timeout_s)
        if tool_calls:
            for tc in tool_calls:
                print(f"  OK: tool_call -> {tc['function']['name']}"
                      f"({tc['function']['arguments']})  耗时 {time.monotonic() - t0:.2f}s")
            return 0
        print(f"  警告: 未产生 tool_call，模型直接回复: {content[:80]}")
        return 1
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1


# ==================== 入口 ====================

def main():
    p = argparse.ArgumentParser(description="PC 端语音交互模式（Sherpa-ONNX + 云端 LLM + web 硬件网关）")
    p.add_argument("--config", default=os.path.join(PC_TEST_DIR, "voice_config.yaml"),
                   help="配置文件路径（默认 voice_config.yaml）")
    p.add_argument("--gateway", help="web 硬件网关地址（覆盖配置/环境变量）")
    p.add_argument("--model", help="覆盖 LLM 模型名")
    p.add_argument("--llm-mode", choices=["local", "siliconflow", "dashscope"],
                   help="覆盖 LLM 引擎模式（默认 siliconflow=硅基流动云端）")
    p.add_argument("--api-key", help="覆盖 LLM API Key（云端模式）")
    p.add_argument("--mic-index", type=int, help="覆盖麦克风设备索引")
    p.add_argument("--self-check", action="store_true", help="运行环境自检后退出")
    p.add_argument("--test-llm", metavar="TEXT", help="向 LLM 发一句话做连通性+工具调用验证")
    p.add_argument("--kws-repl", action="store_true", help="KWS/ASR 识别 REPL（校准唤醒词）")
    p.add_argument("--list-mic", action="store_true", help="列出输入设备后退出")
    args = p.parse_args()

    cfg = load_config(args.config)
    # 局部配置覆盖（也支持 voice_config.local.yaml）
    local = os.path.join(PC_TEST_DIR, "voice_config.local.yaml")
    if os.path.exists(local):
        _merge(cfg, load_config(local))
    if args.gateway:
        cfg["gateway"]["url"] = args.gateway
    if args.model:
        cfg["llm"]["model"] = args.model
    if args.llm_mode:
        cfg["llm"]["mode"] = args.llm_mode
    if args.api_key:
        cfg["llm"]["api_key"] = args.api_key
    if args.mic_index is not None:
        cfg["mic"]["device_index"] = args.mic_index

    # 环境变量覆盖（优先级最高）——Docker Compose 服务发现/外设配置用：
    #   SMART_HOME_WEB_URL / SMART_HOME_LLM_BASE_URL / SMART_HOME_LLM_API_KEY
    #   SMART_HOME_LLM_MODEL / SMART_HOME_LLM_MODE / SMART_HOME_MIC_INDEX
    if os.environ.get("SMART_HOME_WEB_URL"):
        cfg["gateway"]["url"] = os.environ["SMART_HOME_WEB_URL"]
    if os.environ.get("SMART_HOME_LLM_BASE_URL"):
        cfg["llm"]["base_url"] = os.environ["SMART_HOME_LLM_BASE_URL"]
    if os.environ.get("SMART_HOME_LLM_API_KEY"):
        cfg["llm"]["api_key"] = os.environ["SMART_HOME_LLM_API_KEY"]
    if os.environ.get("SMART_HOME_LLM_MODEL"):
        cfg["llm"]["model"] = os.environ["SMART_HOME_LLM_MODEL"]
    if os.environ.get("SMART_HOME_LLM_MODE"):
        cfg["llm"]["mode"] = os.environ["SMART_HOME_LLM_MODE"]
    if os.environ.get("SMART_HOME_MIC_INDEX"):
        cfg["mic"]["device_index"] = int(os.environ["SMART_HOME_MIC_INDEX"])

    if args.list_mic:
        from tts_player import list_input_devices
        for idx, name in list_input_devices():
            print(f"  [{idx}] {name}")
        return
    if args.self_check:
        sys.exit(asyncio.run(self_check(cfg)))
    if args.test_llm:
        sys.exit(asyncio.run(test_llm(cfg, args.test_llm)))
    if args.kws_repl:
        sys.exit(kws_repl(cfg))

    va = VoiceAssistant(cfg)
    try:
        va.load_listener()
    except Exception as e:
        print(f"[启动失败] {e}")
        sys.exit(1)
    try:
        asyncio.run(va.run())
    except KeyboardInterrupt:
        print("\n退出。")


if __name__ == "__main__":
    main()
