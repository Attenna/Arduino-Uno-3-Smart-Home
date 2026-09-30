"""voice_assistant.py — PC 端语音交互模式主编排（Sherpa-ONNX 语音前端）

流程：
    麦克风 → Sherpa-ONNX 双引擎（sherpa_listener.SherpaListener）
        KWS（zipformer 关键词检测）→ 命中「Hey Bota」→ 切 COMMAND + 提示音
        流式 Paraformer ASR + 端点检测 → 整句指令
        FOLLOWUP：回答后 8s 追问窗口，无需再唤醒
    用户指令 → Qwen2.5 LLM 流式 + 工具调用（本地 qwen_server.py 或阿里云百炼）
        delta.content → 按句切分喂 TTS（边生成边播）
        delta.tool_calls → 经 MCP 调 mcp_home_server 控制硬件（JSON 串口指令不变）
    回复文本 → sherpa-onnx VITS 本地流式播放

启动：
    py -3.13 voice_assistant.py                              # 用 voice_config.yaml
    py -3.13 voice_assistant.py --port-a COM7 --port-b COM6
    py -3.13 voice_assistant.py --self-check
    py -3.13 voice_assistant.py --test-llm "开红灯"
    py -3.13 voice_assistant.py --kws-repl
    py -3.13 voice_assistant.py --list-mic
"""
import argparse
import asyncio
import json
import os
import re
import sys
import time
import urllib.request
from typing import Optional

import yaml

# 同目录模块（tts_player 依赖 sounddevice，惰性导入以便依赖不全时自检可运行）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PC_TEST_DIR = os.path.dirname(os.path.abspath(__file__))


# ==================== 语音动作回传 web（与面板等效）====================
# 语音进程独占串口、直连 MCP，web 仪表盘看不到这些调用，状态/历史/全屋模式会
# 落后于真实硬件。动作成功后把结果回传 web（只记账、不重复下发硬件），使语音
# 与面板效果一致。容器内用 SMART_HOME_WEB_URL=http://web:5000。
WEB_URL = os.environ.get("SMART_HOME_WEB_URL", "http://127.0.0.1:5000").rstrip("/")


def _pct255(value, default=0):
    """MCP 工具用 0~255 表示亮度/转速，面板用百分比。"""
    try:
        return max(0, min(100, round(int(value) * 100 / 255)))
    except (TypeError, ValueError):
        return default


def voice_action_payload(name, args):
    """把 MCP 工具调用翻译成面板等效的记账请求；无关工具返回 None。"""
    args = args or {}
    action = str(args.get("action", "")).lower()

    if name == "door":
        if action not in ("open", "close"):
            return None
        return {"device": "door", "status": "open" if action == "open" else "closed"}

    if name == "window":
        if action not in ("open", "close", "normal"):
            return None
        status = {"open": "open", "close": "closed", "normal": "normal"}[action]
        return {"device": "window", "status": status}

    if name == "light":
        if action == "off":
            return {"device": "light", "status": "off", "brightness": 0}
        if action in ("on", "white", "red", "green", "blue",
                      "yellow", "purple", "cyan", "rgb"):
            # 彩色指令面板不跟踪颜色，只记为「开」+亮度
            brightness = _pct255(args.get("value"), 100) or 100
            return {"device": "light", "status": "on", "brightness": brightness}
        return None

    if name == "fan":
        if action == "off":
            return {"device": "fan", "speed": 0}
        if action == "on":
            return {"device": "fan", "speed": 100}
        if action == "set_speed":
            return {"device": "fan", "speed": _pct255(args.get("value"), 50)}
        return None

    return None


def report_voice_action(name, args, timeout=3.0):
    """把语音动作回传 web；失败只提示，不影响语音主流程。"""
    payload = voice_action_payload(name, args)
    if payload is None:
        return
    payload["source"] = "voice"
    try:
        req = urllib.request.Request(
            f"{WEB_URL}/api/devices/manual_report",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
        print(f"[回传] 已同步到仪表盘: {payload}", flush=True)
    except Exception as e:                               # noqa: BLE001
        print(f"[回传] 仪表盘同步失败（不影响硬件动作）: {e}", flush=True)


# ==================== 配置加载 ====================

DEFAULT_CONFIG = {
    "serial": {"port_a": "auto", "port_b": "auto"},
    "llm": {"mode": "local",
            "base_url": "http://127.0.0.1:8000/v1",
            "api_key": None,
            "model": "qwen2.5-3b-instruct-q4_k_m",
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
    # 手动触发对话开始（等价于 KWS 唤醒）：
    #   keyboard=终端按回车；http=POST/GET http://<host>:<port>/trigger
    #   香橙派物理按钮可接 GPIO 守护进程 curl 一下，或手机/浏览器开主页点按钮
    "trigger": {"keyboard": True, "http": True, "host": "0.0.0.0", "port": 8101},
}


# ==================== 手动触发通道（键盘回车 / HTTP / 外部程序）====================

class TriggerBus:
    """跨线程唤醒信号：任意来源 fire()，音频回调每帧 consume() 一次。"""

    def __init__(self):
        import threading
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

    GET  /            状态页（含「开始对话」按钮 + 文本输入框，手机可直接开）
    GET  /state       当前状态 JSON
    GET/POST /trigger 触发一次语音监听（curl/物理按钮/网页均可）
    POST /say         直接下发文本指令（JSON: {"text": "..."}，绕过麦克风直接对话）
    GET  /say?text=.. 同上，GET 形式（方便纯 curl/无 body 的 IoT 设备）
    POST /tool        直接调用 MCP 硬件工具（JSON: {"name":"door","arguments":{...}}）
                       不经 LLM/TTS，静默执行——供 Web 人脸识别等外部系统联动硬件。
    """

    def __init__(self, host: str, port: int, bus: TriggerBus, get_state, submit_text,
                 call_tool=None, on_wake=None):
        import http.server
        import threading
        from urllib.parse import urlparse, parse_qs

        bus_ref, state_ref, say_ref = bus, get_state, submit_text
        tool_ref = call_tool  # 同步回调：(name, arguments) -> (ok: bool, text: str)
        wake_ref = on_wake    # 同步回调：(source) -> None；缺省退回 bus.fire()

        class _Handler(http.server.BaseHTTPRequestHandler):
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

            def _tool(self):
                if tool_ref is None:
                    self._json(503, {"ok": False, "error": "MCP 工具通道不可用"})
                    return
                try:
                    length = int(self.headers.get("Content-Length") or 0)
                    raw = self.rfile.read(length) if length else b"{}"
                    data = json.loads(raw.decode("utf-8") or "{}")
                except Exception:
                    self._json(400, {"ok": False, "error": "JSON 解析失败"})
                    return
                name = data.get("name") if isinstance(data, dict) else None
                arguments = data.get("arguments") if isinstance(data, dict) else None
                if not isinstance(name, str) or not name:
                    self._json(400, {"ok": False, "error": "name 不能为空"})
                    return
                if arguments is None:
                    arguments = {}
                if not isinstance(arguments, dict):
                    self._json(400, {"ok": False, "error": "arguments 必须是对象"})
                    return
                try:
                    ok, text = tool_ref(name, arguments)
                except Exception as e:
                    self._json(500, {"ok": False, "error": f"工具调用异常: {e}"})
                    return
                self._json(200 if ok else 502, {"ok": ok, "name": name, "result": text})

            def do_POST(self):
                path = urlparse(self.path).path
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
                elif path == "/tool":
                    self._tool()
                else:
                    self._json(404, {"ok": False})

            def do_GET(self):
                u = urlparse(self.path)
                path, q = u.path, parse_qs(u.query)
                if path == "/trigger":
                    self._fire()
                elif path == "/say":
                    who = self.headers.get("X-Trigger-Source", "http")
                    self._say((q.get("text") or [""])[0], who)
                elif path == "/state":
                    self._json(200, {"state": state_ref()})
                elif path == "/":
                    body = _TRIGGER_PAGE.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._json(404, {"ok": False})

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


_TRIGGER_PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hey Bota · 控制台</title>
<style>body{font-family:system-ui;margin:0;background:#0f1117;color:#e6e6e6;
display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh}
#s{font-size:20px;margin-bottom:24px;opacity:.8}
button{width:200px;height:200px;border-radius:50%;border:0;font-size:24px;
background:linear-gradient(145deg,#3b82f6,#1d4ed8);color:#fff;box-shadow:0 12px 40px #1d4ed866;margin-bottom:30px}
button:active{transform:scale(.96)}
.row{display:flex;gap:10px;width:min(90vw,460px)}
input{flex:1;font-size:18px;padding:14px 16px;border-radius:12px;border:1px solid #333b4d;
background:#171a23;color:#e6e6e6;outline:none}
input:focus{border-color:#3b82f6}
#send{width:auto;height:auto;border-radius:12px;padding:0 24px;font-size:17px;margin:0}
</style></head>
<body><div id="s">状态：--</div>
<button onclick="go()">开 始<br>语音对话</button>
<div class="row"><input id="t" placeholder="或直接输入文字指令，回车发送"
 onkeydown="if(event.key==='Enter')say()">
<button id="send" onclick="say()">发送</button></div>
<script>
async function refresh(){try{const r=await fetch('/state');
const j=await r.json();document.getElementById('s').textContent='状态：'+j.state}catch(e){}}
async function go(){await fetch('/trigger');setTimeout(refresh,200);setTimeout(refresh,1200)}
async function say(){const t=document.getElementById('t');const v=t.value.trim();if(!v)return;
await fetch('/say',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({text:v})});t.value='';setTimeout(refresh,200)}
refresh();setInterval(refresh,1500);
</script></body></html>"""


def _start_keyboard_console(assistant: "VoiceAssistant") -> None:
    """终端键盘双通道（stdin 为 EOF/管道时静默禁用，避免空转误触发）：

        直接打字后回车 → 文本指令，绕过麦克风直接和大模型对话；
        只按回车（空行）→ 开启语音监听（等价喊唤醒词）。
    """
    import threading

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


# ==================== 通用 OpenAI 兼容 LLM 客户端（流式 + 工具调用）====================

DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_QUANT_TAIL = re.compile(
    r"-(q2_k|q3_k_[sml]|q4_0|q4_k_[ms]|q5_0|q5_k_[ms]|q6_k|q8_0|fp16|f16)$")


def resolve_llm(cfg: dict) -> tuple[str, str]:
    """按 mode 解析出 (base_url, model)；dashscope 模式自动纠正端点与模型名。"""
    mode = cfg["llm"]["mode"]
    base = cfg["llm"]["base_url"].rstrip("/")
    model = cfg["llm"]["model"]
    if mode == "dashscope":
        if "127.0.0.1" in base or "localhost" in base:
            base = DASHSCOPE_BASE       # mode 已切云端但 base_url 忘改：自动纠正
        model = _QUANT_TAIL.sub("", model)  # "qwen2.5-3b-instruct-q4_k_m" → "qwen2.5-3b-instruct"
    return base, model


async def stream_chat(base_url: str, api_key: Optional[str], model: str,
                      messages: list, tools: Optional[list] = None,
                      on_content=None) -> tuple[str, list]:
    """流式调用 OpenAI 兼容 /chat/completions。

    on_content(token) 在每个内容 token 到达时回调（喂 TTS 用）。
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
    content_parts, tc_acc = [], {}
    async with httpx.AsyncClient(timeout=None) as client:
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
    tool_calls = [{
        "id": v["id"] or f"call_{i}",
        "type": "function",
        "function": {"name": v["name"], "arguments": v["arguments"]},
    } for i, v in tc_acc.items()]
    return "".join(content_parts), tool_calls


def load_config(path: Optional[str]) -> dict:
    cfg = {k: dict(v) if isinstance(v, dict) else v for k, v in DEFAULT_CONFIG.items()}
    if path and os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            user = yaml.safe_load(f) or {}
        _merge(cfg, user)
    return cfg


def _merge(base: dict, over: dict) -> None:
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


# ==================== 语音助手主体 ====================

class VoiceAssistant:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.port_a = cfg["serial"]["port_a"]
        self.port_b = cfg["serial"]["port_b"]
        self.llm_mode = cfg["llm"]["mode"]
        self.llm_base_url, self.llm_model = resolve_llm(cfg)
        key = cfg["llm"].get("api_key")
        self.llm_api_key = key if key and key != "none" else os.environ.get("DASHSCOPE_API_KEY")
        self.system_prompt = cfg["llm"]["system_prompt"]
        from tts_player import TtsPlayer  # 惰性导入（依赖 sounddevice）
        self.tts = TtsPlayer(cfg=cfg["sherpa"]["tts"])
        self.wake_words = cfg["wake"]["words"]
        self.command_timeout = cfg["wake"]["command_timeout"]
        self.followup_timeout = cfg["wake"].get("followup_timeout", 8.0)
        self.wake_ack = cfg["wake"]["wake_ack"]
        self.ack_mode = cfg["wake"].get("ack_mode", "chirp")
        self.chirp_freq = int(cfg["wake"].get("chirp_freq", 880))
        self.chirp_ms = int(cfg["wake"].get("chirp_ms", 120))
        self._last_state = None         # 状态变化时才打印，避免刷屏
        self.mic_device = cfg["mic"]["device_index"]

        self.trigger = TriggerBus()     # 手动触发（键盘/HTTP/外部程序）
        self.trigger_http = None

        self.listener = None            # sherpa_listener.SherpaListener
        self.stream = None
        self.state = "IDLE"
        self.command_state_start = 0.0
        self.command_queue: "queue.Queue[str]" = __import__("queue").Queue()

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
            # MCP 硬件工具与 HTTP /tool、/say 仍正常工作。
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
            import threading
            threading.Timer(self.command_timeout, self._idle_if_command).start()

    def _idle_if_command(self):
        """无麦克风部署下 COMMAND 状态的超时回收（音频回调不在时使用）。"""
        if self.state == "COMMAND":
            self.state = "IDLE"
            self._emit_state("IDLE")

    def _emit_state(self, new_state):
        """状态变化时打印醒目状态行。"""
        if new_state != self._last_state:
            self._last_state = new_state
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
        self.state = "COMMAND"
        self.command_state_start = now
        if manual and self.listener:
            self.listener.reset_asr()   # 手动触发：丢弃触发前录入的半句噪声
        self._ack()
        tag = "手动触发" if manual else "KWS 命中"
        print(f"\n  [⭐ 唤醒成功！] {tag}「{keyword}」→ 已切换到指令模式", flush=True)
        self._emit_state("COMMAND")

    def submit_text(self, text: str, source: str = "键盘") -> None:
        """键盘/HTTP 直接输入文本指令（绕过 ASR）：打断播报、清空残句、入队对话。"""
        text = (text or "").strip()
        if not text:
            return
        if self.tts.is_busy():
            self.tts.stop()
        if self.state == "THINKING":
            print(f"\n  [📥 {source}指令已排队] {text}", flush=True)
        else:
            print(f"\n  [📥 {source}文本指令] {text}", flush=True)
        self.state = "THINKING"
        self._last_state = "THINKING"  # 抑制随后重复的思考状态行
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
                self.state = "THINKING"
                self._emit_state("THINKING")
            else:
                # 只有唤醒词、没说指令：留在 COMMAND 等下一句
                print("  [💬] 只听到唤醒词，继续听指令...", flush=True)
        elif self.state == "FOLLOWUP":
            # 追问模式：无需唤醒词，直接当指令
            self.command_queue.put(text)
            print(f"  [✅ 追问] {text}  → 交给大模型处理", flush=True)
            self.state = "THINKING"
            self._emit_state("THINKING")

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
                    shown = text if len(text) <= 30 else text[-30:]
                    print(f"  [听到] {shown}", end="\r", flush=True)
                elif kind == "final":
                    self._on_final(text)
            # 超时检查（由音频帧驱动）
            if self.state == "COMMAND" and now - self.command_state_start > self.command_timeout:
                self.state = "IDLE"
                print("\n  [⏰ 超时] 未收到指令，回到待唤醒状态", flush=True)
                self._emit_state("IDLE")
            elif self.state == "FOLLOWUP" and now - self.command_state_start > self.followup_timeout:
                self.state = "IDLE"
                self._emit_state("IDLE")
        except Exception as e:
            print(f"\n[音频] 回调异常: {e}", flush=True)

    # ── Qwen 流式 + 工具调用 ──
    async def stream_llm(self, messages, tools):
        """流式调用 LLM，token 边生成边喂 TTS；返回 (content, tool_calls)。"""
        try:
            content, tool_calls = await stream_chat(
                self.llm_base_url, self.llm_api_key, self.llm_model,
                messages, tools, on_content=self.tts.feed_token)
            return content, tool_calls
        except Exception as e:
            print(f"[LLM] 调用失败: {e}", flush=True)
            self.tts.speak("大模型出错了")
            return "", []

    async def handle_command(self, user_text, session, llm_tools):
        print(f"[你] {user_text}", flush=True)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_text},
        ]
        final_content = ""
        for rnd in range(3):
            content, tool_calls = await self.stream_llm(messages, llm_tools)
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
                try:
                    res = await session.call_tool(name, args)
                    result_text = ""
                    for c in (res.content or []):
                        txt = getattr(c, "text", None)
                        if txt is None and isinstance(c, dict):
                            txt = c.get("text")
                        if txt:
                            result_text += txt
                    if not result_text:
                        result_text = "(工具无文本输出)"
                except Exception as e:
                    result_text = f"error: 工具执行异常 {e}"
                print(f"[工具] {name} -> {result_text}", flush=True)
                if not result_text.lower().startswith("error"):
                    # 与面板等效：把动作结果同步给仪表盘（状态/历史/切手动）。
                    # 只对语音自己发起的调用回传；web 经 /tool 转发的不回传，
                    # 否则面板的自动调节会被误判成「用户手动操作」。
                    await asyncio.to_thread(report_voice_action, name, args)
                messages.append({"role": "tool", "tool_call_id": tc["id"],
                                 "content": result_text})
        self.tts.flush()
        # 若本轮有工具调用，最后再请求一次大模型生成自然语言总结回复
        if final_content == "" and any(m.get("role") == "tool" for m in messages):
            content, _ = await self.stream_llm(messages, llm_tools)
            if content:
                final_content = content
                print(f"[助手] {content}", flush=True)
        if not final_content:
            print("[助手] (无文字回复)", flush=True)
        await asyncio.sleep(0.2)

    # ── 主循环 ──
    async def run(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server_script = os.path.join(PC_TEST_DIR, "mcp_home_server.py")
        args = [server_script]
        if self.port_a and self.port_a != "auto":
            args += ["--port-a", self.port_a]
        if self.port_b and self.port_b != "auto":
            args += ["--port-b", self.port_b]
        params = StdioServerParameters(
            command=sys.executable, args=args, cwd=PC_TEST_DIR)

        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                llm_tools = [{
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description or "",
                        "parameters": t.inputSchema or {"type": "object", "properties": {}},
                    },
                } for t in tools_result.tools]
                print(f"[MCP] 已加载 {len(llm_tools)} 个工具: "
                      f"{[t['function']['name'] for t in llm_tools]}", flush=True)

                loop = asyncio.get_running_loop()
                allowed_tools = {t["function"]["name"] for t in llm_tools}

                def _direct_call_tool(name, arguments):
                    """供 POST /tool 使用：跨线程直调 MCP，不经 LLM/TTS。"""
                    if name not in allowed_tools:
                        return False, f"未知工具: {name}"

                    async def _do():
                        res = await session.call_tool(name, arguments)
                        text = ""
                        for c in (res.content or []):
                            part = getattr(c, "text", None)
                            if part is None and isinstance(c, dict):
                                part = c.get("text")
                            if part:
                                text += part
                        return text or "(工具无文本输出)"

                    fut = asyncio.run_coroutine_threadsafe(_do(), loop)
                    try:
                        text = fut.result(timeout=15)
                    except Exception as e:
                        return False, f"工具执行异常: {e}"
                    return (not text.startswith("error")), text

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
                            call_tool=_direct_call_tool,
                            on_wake=self._manual_wake)
                    except Exception as e:
                        print(f"[触发] HTTP 接口启动失败（不影响语音）: {e}", flush=True)

                self._start_mic()
                print("=" * 56, flush=True)
                print("  🎤 语音助手已启动（Sherpa-ONNX 前端 + Qwen2.5-3B）", flush=True)
                print("  麦克风: " + (f"索引 {self.mic_device}" if self.mic_device is not None else "系统默认"), flush=True)
                print("  唤醒词(KWS): " + " / ".join(self.listener.keywords), flush=True)
                if tcfg.get("keyboard", True):
                    print("  ⌨️  键盘对话: 直接打字回车发送指令；空回车=开始语音监听", flush=True)
                if self.trigger_http is not None:
                    p = self.trigger_http.port
                    print(f"  🌐 HTTP 接口: http://<本机IP>:{p}/ （网页）", flush=True)
                    print(f"             语音触发 POST/GET /trigger；文本指令 POST /say  {{\"text\":\"...\"}}",
                          flush=True)
                    print(f"             硬件直调 POST /tool {{\"name\":\"door\",\"arguments\":{{...}}}}（静默，不经语音）",
                          flush=True)
                print("=" * 56, flush=True)
                self._emit_state("IDLE")
                try:
                    while True:
                        text = await loop.run_in_executor(None, self.command_queue.get)
                        if text is None:
                            break
                        try:
                            await self.handle_command(text, session, llm_tools)
                        except Exception as e:
                            print(f"[错误] 处理指令失败: {e}", flush=True)
                            self.tts.speak("出错了，请重说")
                        finally:
                            # 处理完毕，进入追问模式（followup_timeout 内可直接说话，无需重新唤醒）
                            self.state = "FOLLOWUP"
                            self.command_state_start = time.time()
                            if self.listener:
                                self.listener.reset_asr()  # 清掉思考期间误录的半句
                            print(f"\n  [💬 可追问] {self.followup_timeout:.0f}s 内可直接说下一句，超时回到待唤醒", flush=True)
                except (KeyboardInterrupt, asyncio.CancelledError):
                    pass
        try:
            self.stream.stop()
        except Exception:
            pass
        if self.trigger_http is not None:
            self.trigger_http.shutdown()
        self.tts.shutdown()


# ==================== 自检 / REPL 子命令 ====================

async def self_check(cfg: dict) -> int:
    print("=" * 60)
    print("  语音模式自检（Sherpa-ONNX）")
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
    try:
        import sounddevice as sd
        sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                       device=cfg["mic"]["device_index"]).start()
        time.sleep(1.0)
        print("    OK: 麦克风可读")
    except Exception as e:
        print(f"    FAIL: {e}")
        ok = False

    # (d) LLM 引擎（Qwen2.5）可达
    print("\n[d] LLM 引擎（Qwen2.5）可达性...", flush=True)
    try:
        import httpx
        base, _model = resolve_llm(cfg)
        mode = cfg["llm"]["mode"]
        headers = {}
        key = cfg["llm"].get("api_key")
        api_key = key if key and key != "none" else os.environ.get("DASHSCOPE_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{base}/models", headers=headers)
            ids = [m.get("id") for m in r.json().get("data", [])]
            want = cfg["llm"]["model"]
            if mode == "dashscope":
                if any(i and i.startswith("qwen") for i in ids):
                    print(f"    OK: 百炼端点可达，含 Qwen 模型（示例: {ids[:3]}）")
                else:
                    print(f"    FAIL: 端点返回模型 {ids[:5]}，未找到 qwen 系列")
                    ok = False
            else:
                if want in ids:
                    print(f"    OK: 本地 Qwen 服务已加载 {want}")
                else:
                    print(f"    FAIL: 本地服务返回模型 {ids}，期望 {want}")
                    print("    → 先启动: py -3.13 qwen_server.py（或双击 start_voice.bat）")
                    ok = False
    except Exception as e:
        print(f"    FAIL: {e}")
        if cfg["llm"]["mode"] == "local":
            print("    → 本地模式先启动: py -3.13 qwen_server.py（模型未下载则先跑 download_qwen.py）")
        else:
            print("    → 百炼模式需配置 DASHSCOPE_API_KEY 或 config llm.api_key")
        ok = False

    # (e) MCP server 工具数
    print("\n[e] MCP server 工具暴露...", flush=True)
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        params = StdioServerParameters(
            command=sys.executable,
            args=[os.path.join(PC_TEST_DIR, "mcp_home_server.py"), "--no-serial"],
            cwd=PC_TEST_DIR)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tr = await s.list_tools()
                names = [t.name for t in tr.tools]
                print(f"    OK: {len(names)} 个工具: {names}")
                if len(names) < 9:
                    print("    警告: 期望 9 个工具")
    except Exception as e:
        print(f"    FAIL: {e}")
        ok = False

    # (f) 串口探测
    print("\n[f] Arduino 串口探测...", flush=True)
    try:
        import serial
        import serial.tools.list_ports as sp
        ports = [(p.device, p.description) for p in sp.comports()]
        if not ports:
            print("    警告: 未发现任何 COM 端口")
        for dev, desc in ports:
            hit = ""
            try:
                ser = serial.Serial(dev, 115200, timeout=0.3)
                time.sleep(0.1)
                ser.reset_input_buffer()
                ser.write(b'{"cmd":"system","action":"who"}\n')
                ser.write(b"WHO\n")
                deadline = time.time() + 0.5
                while time.time() < deadline:
                    ln = ser.readline().decode("utf-8", "replace")
                    if "MODULE_A" in ln:
                        hit = "Module_A"
                        break
                    if "MODULE_B" in ln:
                        hit = "Module_B"
                        break
                ser.close()
            except Exception as e:
                hit = f"探测失败 {e}"
            print(f"    {dev} ({desc}) -> {hit or '无响应'}")
    except Exception as e:
        print(f"    FAIL: {e}")

    print("\n" + "=" * 60)
    print("  自检" + ("通过 ✓" if ok else "存在失败项 ✗（见上方提示）"))
    print("=" * 60)
    return 0 if ok else 1


def kws_repl(cfg: dict) -> int:
    """KWS + ASR 实时 REPL：说「Hey Bota」测唤醒，说话测识别（Ctrl+C 退出）。"""
    import numpy as np
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
    """一次性验证 Qwen 引擎：①普通对话流式输出 ②工具调用探测。"""
    base, model = resolve_llm(cfg)
    key = cfg["llm"].get("api_key")
    api_key = key if key and key != "none" else os.environ.get("DASHSCOPE_API_KEY")
    print(f"[LLM] 模式={cfg['llm']['mode']}  模型={model}  端点={base}")

    print(f"\n[测试1] 普通对话（流式输出）: {text}")
    try:
        content, _ = await stream_chat(base, api_key, model,
                                       [{"role": "user", "content": text}],
                                       on_content=lambda t: print(t, end="", flush=True))
        print()
        if not content.strip():
            print("  FAIL: 无内容返回")
            return 1
        print("  OK: 流式回复正常")
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
        content, tool_calls = await stream_chat(
            base, api_key, model,
            [{"role": "system", "content": "你是智能家居助手，必须用工具执行硬件操作，禁止只回复文字。"},
             {"role": "user", "content": "把灯调成红色"}],
            tools=[tool])
        if tool_calls:
            for tc in tool_calls:
                print(f"  OK: tool_call -> {tc['function']['name']}({tc['function']['arguments']})")
            return 0
        print(f"  警告: 未产生 tool_call，模型直接回复: {content[:80]}")
        return 1
    except Exception as e:
        print(f"  FAIL: {e}")
        return 1


# ==================== 入口 ====================

def main():
    p = argparse.ArgumentParser(description="PC 端语音交互模式（Sherpa-ONNX + Qwen2.5）")
    p.add_argument("--config", default=os.path.join(PC_TEST_DIR, "voice_config.yaml"),
                   help="配置文件路径（默认 voice_config.yaml）")
    p.add_argument("--port-a", help="覆盖 Module A 串口")
    p.add_argument("--port-b", help="覆盖 Module B 串口")
    p.add_argument("--model", help="覆盖 LLM 模型名")
    p.add_argument("--llm-mode", choices=["local", "dashscope"], help="覆盖 LLM 引擎模式")
    p.add_argument("--api-key", help="覆盖 LLM API Key（百炼模式）")
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
    if args.port_a:
        cfg["serial"]["port_a"] = args.port_a
    if args.port_b:
        cfg["serial"]["port_b"] = args.port_b
    if args.model:
        cfg["llm"]["model"] = args.model
    if args.llm_mode:
        cfg["llm"]["mode"] = args.llm_mode
    if args.api_key:
        cfg["llm"]["api_key"] = args.api_key
    if args.mic_index is not None:
        cfg["mic"]["device_index"] = args.mic_index

    # 环境变量覆盖（优先级最高）——Docker Compose 服务发现/外设配置用：
    #   SMART_HOME_LLM_BASE_URL / SMART_HOME_LLM_API_KEY / SMART_HOME_LLM_MODEL
    #   SMART_HOME_MIC_INDEX / SMART_HOME_PORT_A / SMART_HOME_PORT_B
    if os.environ.get("SMART_HOME_LLM_BASE_URL"):
        cfg["llm"]["base_url"] = os.environ["SMART_HOME_LLM_BASE_URL"]
    if os.environ.get("SMART_HOME_LLM_API_KEY"):
        cfg["llm"]["api_key"] = os.environ["SMART_HOME_LLM_API_KEY"]
    if os.environ.get("SMART_HOME_LLM_MODEL"):
        cfg["llm"]["model"] = os.environ["SMART_HOME_LLM_MODEL"]
    if os.environ.get("SMART_HOME_MIC_INDEX"):
        cfg["mic"]["device_index"] = int(os.environ["SMART_HOME_MIC_INDEX"])
    if os.environ.get("SMART_HOME_PORT_A"):
        cfg["serial"]["port_a"] = os.environ["SMART_HOME_PORT_A"]
    if os.environ.get("SMART_HOME_PORT_B"):
        cfg["serial"]["port_b"] = os.environ["SMART_HOME_PORT_B"]

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
