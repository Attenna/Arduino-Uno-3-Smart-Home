"""qwen_server.py — 本地 Qwen2.5 OpenAI 兼容推理服务（llama.cpp 后端）

国内合规说明：
    - 模型权重经魔搭社区 ModelScope（阿里巴巴，国内合法渠道）下载：见 download_qwen.py
    - 推理由本地 llama.cpp（llama-cpp-python）完成，运行期不访问任何外部服务
    - 对外暴露 OpenAI 兼容接口：
        GET  /v1/models
        POST /v1/chat/completions   （流式 + Qwen 原生 <tool_call> 工具调用解析）

启动：
    py -3.13 qwen_server.py                       # 模型路径取 voice_config.yaml llm.local
    py -3.13 qwen_server.py --model models/qwen/qwen2.5-3b-instruct-q4_k_m.gguf --port 8000
"""
import argparse
import datetime
import glob
import json
import os
import sys
import time
import uuid

# ── CUDA 运行时 DLL 路径自动注入（Windows，须在 import llama_cpp 之前）──
# 预编译 CUDA wheel 依赖系统 CUDA 12.x 运行时（cudart/cublas），
# 从 CUDA_PATH 或默认安装目录找到 bin 并加入 PATH（12.x 内小版本兼容）。
if sys.platform == "win32":
    _cuda_candidates = []
    if os.environ.get("CUDA_PATH"):
        _cuda_candidates.append(os.path.join(os.environ["CUDA_PATH"], "bin"))
    _cuda_candidates += sorted(
        glob.glob(r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.*\bin"),
        reverse=True)
    for _cb in _cuda_candidates:
        if os.path.isfile(os.path.join(_cb, "cudart64_12.dll")):
            os.environ["PATH"] = _cb + os.pathsep + os.environ.get("PATH", "")
            break

try:
    from llama_cpp import Llama
    import jinja2
except ImportError as e:
    print(f"[错误] 依赖缺失（{e}）：", file=sys.stderr)
    print("  py -3.13 -m pip install llama-cpp-python jinja2 -i https://mirrors.aliyun.com/pypi/simple/",
          file=sys.stderr)
    sys.exit(1)

try:
    import uvicorn
    from fastapi import FastAPI, Request
    from fastapi.responses import StreamingResponse
except ImportError:
    print("[错误] 未安装 fastapi/uvicorn：", file=sys.stderr)
    print("  py -3.13 -m pip install fastapi uvicorn -i https://mirrors.aliyun.com/pypi/simple/",
          file=sys.stderr)
    sys.exit(1)

PC_TEST_DIR = os.path.dirname(os.path.abspath(__file__))

_llm = None
_MODEL_ID = "qwen2.5-3b-instruct-q4_k_m"
_TPL = None

TAG_OPEN = "<tool_call>"
TAG_CLOSE = "</tool_call>"


def load_model(path: str, n_ctx: int, n_threads: int, n_gpu_layers: int,
               model_id: str = None):
    global _llm, _MODEL_ID
    import llama_cpp
    gpu_ok = bool(llama_cpp.llama_supports_gpu_offload())
    if n_gpu_layers > 0:
        if gpu_ok:
            print(f"[Qwen] GPU 推理已启用（CUDA 后端可用，卸载 {n_gpu_layers} 层到显卡）",
                  file=sys.stderr)
        else:
            print("[Qwen] 警告：配置了 n_gpu_layers>0 但当前 llama-cpp-python 无 CUDA 后端，"
                  "回退 CPU（请安装 cu124 GPU 版 wheel）", file=sys.stderr)
            n_gpu_layers = 0
    else:
        print("[Qwen] CPU 推理模式（n_gpu_layers=0）", file=sys.stderr)
    print(f"[Qwen] 加载 {path} ...", file=sys.stderr)
    kwargs = dict(model_path=path, n_ctx=n_ctx, n_threads=n_threads,
                  n_gpu_layers=n_gpu_layers, verbose=False)
    if gpu_ok and n_gpu_layers > 0:
        kwargs["flash_attn"] = True   # GPU 上开启 FlashAttention 加速
    _llm = Llama(**kwargs)
    _MODEL_ID = model_id or os.path.splitext(os.path.basename(path))[0]
    _init_template()
    print(f"[Qwen] 就绪：模型 id = {_MODEL_ID}（device={'GPU' if gpu_ok and n_gpu_layers > 0 else 'CPU'}）",
          file=sys.stderr)


def _raise_template_error(msg):
    raise ValueError(msg)


def _init_template():
    """从 GGUF 元数据取内置 Qwen 聊天模板（含 # Tools 渲染逻辑）。"""
    global _TPL
    src = _llm.metadata.get("tokenizer.chat_template")
    if not src:
        print("[Qwen] 警告：GGUF 无内置聊天模板，退回手工 ChatML（工具调用不可用）",
              file=sys.stderr)
        return
    env = jinja2.Environment(trim_blocks=True, lstrip_blocks=True)
    env.filters["tojson"] = lambda v, **kw: json.dumps(v, ensure_ascii=False)
    env.globals["raise_exception"] = _raise_template_error
    env.globals["strftime_now"] = lambda fmt: datetime.datetime.now().strftime(fmt)
    _TPL = env.from_string(src)
    print("[Qwen] 已加载内置聊天模板（支持工具渲染）", file=sys.stderr)


def build_prompt(messages, tools):
    """渲染最终 prompt：优先内置 Qwen 模板（含工具定义），失败退回手工 ChatML。"""
    if _TPL is not None:
        try:
            return _TPL.render(messages=messages, tools=tools,
                               add_generation_prompt=True)
        except Exception as e:
            print(f"[Qwen] 模板渲染失败，退回 ChatML: {e}", file=sys.stderr)
    text = ""
    for m in messages:
        text += f"<|im_start|>{m.get('role')}\n{m.get('content') or ''}<|im_end|>\n"
    return text + "<|im_start|>assistant\n"


def _norm_braces(s: str) -> str:
    """小模型常把模板示例里的 {{"..."}} 双层括号学去；把外层双括号剥成单层。"""
    s = s.strip()
    if s.startswith("{{") and s.endswith("}}"):
        s = s[1:-1].strip()
    return s


def _coerce_tool_obj(obj):
    if not isinstance(obj, dict):
        return None
    name = obj.get("name")
    if not name:
        return None
    args = obj.get("arguments", {})
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    if not isinstance(args, dict):
        args = {}
    return name, json.dumps(args, ensure_ascii=False)


def _parse_tool_json(body: str):
    """解析 <tool_call> 标签体内或裸输出的 {"name":..., "arguments":{...}}。

    兼容小模型常见变体：{{"name":...}} 双大括号、前后杂文本。
    """
    s = _norm_braces(body)
    obj = None
    if s.startswith("{") and s.endswith("}"):
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            obj = None
    if obj is None:
        l, r = s.find("{"), s.rfind("}")
        if l < 0 or r <= l:
            return None
        try:
            obj = json.loads(_norm_braces(s[l:r + 1]))
        except json.JSONDecodeError:
            return None
    return _coerce_tool_obj(obj)


def _extract_tool_anywhere(text: str):
    """从整段文本（可能夹杂自然语言/双括号）里扫描第一个合法工具调用 JSON。

    1.5B 小模型常见输出：先答一句"好的，我这就调灯"，再裸吐 JSON，
    或把 JSON 写成 {{...}}。逐 '{' 起点 + 括号配对尝试解析。
    """
    if not text:
        return None
    s = _norm_braces(text)
    for i, ch in enumerate(s):
        if ch != "{":
            continue
        depth = 0
        for j in range(i, len(s)):
            if s[j] == "{":
                depth += 1
            elif s[j] == "}":
                depth -= 1
                if depth == 0:
                    cand = _norm_braces(s[i:j + 1])
                    try:
                        obj = json.loads(cand)
                    except json.JSONDecodeError:
                        break  # 这个起点不是合法 JSON，换下一个 '{'
                    parsed = _coerce_tool_obj(obj)
                    if parsed:
                        return parsed
                    break
    return None


# 1.5B 对模板里抽象说明遵从度差，给一个"填好的"单层括号实例，显著提高格式命中率
_TOOL_RULE_SUFFIX = """

# 工具调用（最高优先级，必须照做）
- 需要操作硬件或查询传感器时，禁止只用自然语言答应，必须立即输出一次工具调用。
- 严格使用单层大括号（写成两层 {{ }} 是错的），格式：
<tool_call>
{"name": "函数名", "arguments": {"参数名": "参数值"}}
</tool_call>
- 示例：用户说"把灯调成红色"，你只能输出：
<tool_call>
{"name": "light", "arguments": {"action": "red"}}
</tool_call>"""


def _inject_tool_rules(messages, tools):
    """有工具时把具体调用示例追加进 system 消息（无则新建一条）。"""
    if not tools:
        return messages
    out = list(messages)
    for m in out:
        if m.get("role") == "system":
            m["content"] = (m.get("content") or "") + _TOOL_RULE_SUFFIX
            return out
    return [{"role": "system", "content": _TOOL_RULE_SUFFIX.strip()}] + out


app = FastAPI(title="qwen-local-server")


@app.get("/v1/models")
def models():
    return {"object": "list",
            "data": [{"id": _MODEL_ID, "object": "model", "owned_by": "local"}]}


@app.post("/v1/chat/completions")
async def chat_completions(req: Request):
    body = await req.json()
    messages = body.get("messages", [])
    tools = body.get("tools") or None
    messages = _inject_tool_rules(messages, tools)
    stream = bool(body.get("stream"))
    max_tokens = int(body.get("max_tokens") or 512)
    temperature = float(body.get("temperature") if body.get("temperature") is not None else 0.7)
    top_p = float(body.get("top_p") if body.get("top_p") is not None else 0.8)

    prompt = build_prompt(messages, tools)
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    if not stream:
        out = _llm.create_completion(prompt=prompt, max_tokens=max_tokens,
                                     temperature=temperature, top_p=top_p,
                                     stop=["<|im_end|>"])
        text = out["choices"][0]["text"] or ""
        content_parts, tool_calls = [], []
        rest = text
        while True:
            i = rest.find(TAG_OPEN)
            if i < 0:
                break
            content_parts.append(rest[:i])
            rest = rest[i + len(TAG_OPEN):]
            j = rest.find(TAG_CLOSE)
            if j < 0:
                parsed, rest = _parse_tool_json(rest), ""
            else:
                parsed, rest = _parse_tool_json(rest[:j]), rest[j + len(TAG_CLOSE):]
            if parsed:
                name, args_json = parsed
                tool_calls.append({"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                                   "function": {"name": name, "arguments": args_json}})
        if not tool_calls and tools:      # 无标签：从整段文本（含夹杂自然语言）兜底抽取
            parsed = _extract_tool_anywhere(text)
            if parsed:
                name, args_json = parsed
                tool_calls.append({"id": f"call_{uuid.uuid4().hex[:8]}", "type": "function",
                                   "function": {"name": name, "arguments": args_json}})
        # 纯文本部分 = 各 <tool_call> 之前的文本 + 循环结束后剩余的尾部文本；
        # 普通聊天（无工具标签）时 content_parts 为空、rest 即完整回复
        msg = {"role": "assistant",
               "content": ("".join(content_parts) + rest).strip()}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return {"id": cid, "object": "chat.completion", "created": created,
                "model": _MODEL_ID,
                "choices": [{"index": 0, "message": msg,
                             "finish_reason": "tool_calls" if tool_calls else "stop"}],
                "usage": out.get("usage", {})}

    return StreamingResponse(
        _sse_stream(prompt, max_tokens, temperature, top_p, cid, created, tools),
        media_type="text/event-stream")


def _sse_stream(prompt, max_tokens, temperature, top_p, cid, created, tools=None):
    def emit(delta, finish=None):
        chunk = {"id": cid, "object": "chat.completion.chunk", "created": created,
                 "model": _MODEL_ID,
                 "choices": [{"index": 0, "delta": delta, "logprobs": None,
                              "finish_reason": finish}]}
        return f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"

    def gen():
        yield emit({"role": "assistant", "content": ""})
        tools_emitted = 0
        buf = ""
        emitted = []          # 已作为 content 流出的文本（收尾兜底抽取用）
        in_tool = False

        def say(txt):
            emitted.append(txt)
            return emit({"content": txt})
        # 工具轮先判头：若以 { 开头则整段缓冲（小模型常裸吐 JSON 不带标签）
        json_mode = tools is not None
        stream = _llm.create_completion(prompt=prompt, stream=True,
                                        max_tokens=max_tokens,
                                        temperature=temperature, top_p=top_p,
                                        stop=["<|im_end|>"])
        for chunk in stream:
            piece = chunk["choices"][0].get("text") or ""
            if not piece:
                continue
            buf += piece
            while True:
                if json_mode:
                    s = buf.lstrip()
                    if s and not s.startswith("{"):
                        json_mode = False    # 普通文本/标签开头 → 回流式
                    break
                if not in_tool:
                    i = buf.find(TAG_OPEN)
                    if i >= 0:
                        pre, buf = buf[:i], buf[i + len(TAG_OPEN):]
                        in_tool = True
                        if pre.strip():
                            yield say(pre)
                        continue
                    hold = len(TAG_OPEN) - 1    # 扣住可能是半截标签的尾巴
                    if len(buf) > hold:
                        outp, buf = buf[:-hold], buf[-hold:]
                        if outp:
                            yield say(outp)
                    break
                else:
                    j = buf.find(TAG_CLOSE)
                    if j < 0:
                        break
                    body, buf = buf[:j], buf[j + len(TAG_CLOSE):]
                    in_tool = False
                    parsed = _parse_tool_json(body)
                    if parsed:
                        name, args_json = parsed
                        yield emit({"tool_calls": [{
                            "index": tools_emitted,
                            "id": f"call_{uuid.uuid4().hex[:8]}",
                            "type": "function",
                            "function": {"name": name, "arguments": args_json}}]})
                        tools_emitted += 1
                    else:
                        yield say(body)   # 解析失败回退为文本
        # 收尾：残留 buffer 处理
        if json_mode:
            parsed = _parse_tool_json(buf)
            if parsed:
                name, args_json = parsed
                yield emit({"tool_calls": [{
                    "index": tools_emitted,
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": name, "arguments": args_json}}]})
                tools_emitted += 1
            elif buf.strip():
                yield say(buf)
        elif in_tool and buf.strip():
            parsed = _parse_tool_json(buf)
            if parsed:
                name, args_json = parsed
                yield emit({"tool_calls": [{
                    "index": tools_emitted,
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": name, "arguments": args_json}}]})
                tools_emitted += 1
            else:
                yield say(buf)
        elif buf.strip():
            yield say(buf)
        # 最终兜底：有工具但一个调用都没解析出来 → 从全部已流文本里扫描
        # （1.5B 可能先答一句再裸吐 JSON，或把 JSON 写成 {{...}}）
        if tools and tools_emitted == 0:
            parsed = _extract_tool_anywhere("".join(emitted))
            if parsed:
                name, args_json = parsed
                yield emit({"tool_calls": [{
                    "index": 0,
                    "id": f"call_{uuid.uuid4().hex[:8]}",
                    "type": "function",
                    "function": {"name": name, "arguments": args_json}}]})
                tools_emitted += 1
        yield emit({}, "tool_calls" if tools_emitted else "stop")
        yield "data: [DONE]\n\n"

    return gen()


def _load_yaml_config():
    """读取 voice_config.yaml 的 llm.local 段作为默认参数（不存在则返回 {}）。"""
    cfg_path = os.path.join(PC_TEST_DIR, "voice_config.yaml")
    try:
        import yaml
        with open(cfg_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("llm", {}).get("local", {}) or {}
    except Exception:
        return {}


def main():
    global _MODEL_ID
    local_cfg = _load_yaml_config()
    default_model = local_cfg.get(
        "gguf_path",
        os.path.join(PC_TEST_DIR, "models", "qwen",
                     "qwen2.5-3b-instruct-q4_k_m.gguf"))
    if not os.path.isabs(default_model):
        default_model = os.path.join(PC_TEST_DIR, default_model)

    p = argparse.ArgumentParser(description="本地 Qwen2.5 OpenAI 兼容服务")
    p.add_argument("--model", default=default_model, help="GGUF 模型路径")
    p.add_argument("--model-id", help="对外暴露的模型 id（默认取文件名去后缀）")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=int(local_cfg.get("port", 8000)))
    p.add_argument("--n-ctx", type=int, default=int(local_cfg.get("n_ctx", 8192)))
    p.add_argument("--n-threads", type=int, default=int(local_cfg.get("n_threads", 0)),
                   help="0=自动")
    p.add_argument("--n-gpu-layers", type=int,
                   default=int(local_cfg.get("n_gpu_layers", 0)),
                   help="卸载到 GPU 的层数，0=纯 CPU，99=全部层")
    p.add_argument("--smoke", action="store_true",
                   help="冒烟测试：加载模型并生成 1 个 token 后退出（部署脚本验证用）")
    args = p.parse_args()

    if not os.path.isfile(args.model):
        print(f"[错误] GGUF 模型不存在: {args.model}", file=sys.stderr)
        print("  先运行: py -3.13 download_qwen.py （经 ModelScope 国内渠道下载）",
              file=sys.stderr)
        sys.exit(1)
    load_model(args.model, args.n_ctx, args.n_threads, args.n_gpu_layers, args.model_id)
    if args.smoke:
        import llama_cpp
        device = "GPU" if (bool(llama_cpp.llama_supports_gpu_offload())
                           and args.n_gpu_layers > 0) else "CPU"
        _llm.create_completion(prompt="你", max_tokens=1)
        print(f"[SMOKE_OK] device={device}", file=sys.stderr)
        sys.exit(0)
    print(f"[Qwen] 监听 http://{args.host}:{args.port}/v1", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
