"""sherpa_listener.py — Sherpa-ONNX 音频前端：KWS 唤醒 + 流式 ASR

一条麦克风流同时喂两条引擎：
    KeywordSpotter（zipformer-wenetspeech）→ 唤醒词事件（声学级唤醒，非文本匹配）
    OnlineRecognizer（streaming Zipformer transducer INT8，端点检测）→ 流式识别事件

事件由调用方在音频回调里消费：
    ("wake",    "Hey Bota")   — KWS 命中
    ("partial", "把灯")       — ASR 中间结果（实时显示用）
    ("final",   "把灯调成蓝色") — 端点切分出的整句

模型目录结构（见 download_sherpa_models.py）：
    models/sherpa/kws/     encoder.onnx decoder.onnx joiner.onnx tokens.txt keywords.txt
    models/sherpa/asr/     encoder.onnx decoder.onnx joiner.onnx tokens.txt（transducer）
                           （无 joiner.onnx 时回退 paraformer：encoder+decoder）
"""
import os

import numpy as np

_SAMPLE_RATE = 16000


class SherpaListener:
    """KWS + 流式 ASR 双引擎前端。线程安全假定：accept() 只在音频回调线程调用。"""

    def __init__(self, cfg: dict):
        import sherpa_onnx

        s = cfg["sherpa"]
        kws_dir = _abspath(s["kws"]["model_dir"])
        asr_dir = _abspath(s["asr"]["model_dir"])

        # ── KWS（唤醒词）──
        keywords_file = _abspath(s["kws"]["keywords_file"])
        self.kws = sherpa_onnx.KeywordSpotter(
            tokens=os.path.join(kws_dir, "tokens.txt"),
            encoder=os.path.join(kws_dir, "encoder.onnx"),
            decoder=os.path.join(kws_dir, "decoder.onnx"),
            joiner=os.path.join(kws_dir, "joiner.onnx"),
            keywords_file=keywords_file,
            keywords_score=float(s["kws"].get("keywords_score", 1.5)),
            keywords_threshold=float(s["kws"].get("keywords_threshold", 0.25)),
            num_threads=int(s.get("num_threads", 2)),
            provider=s.get("provider", "cpu"),
        )
        self.kws_stream = self.kws.create_stream()
        # @ 后的内部名不能含空格（声学词表限制），下划线在对外事件里还原为空格
        # 去重：多个音近变体可映射同一个显示名（Hey_Bota ×4 → "Hey Bota"）
        self.keywords = []
        for l in open(keywords_file, encoding="utf-8"):
            if l.strip() and "@" in l:
                name = l.split("@", 1)[1].strip().replace("_", " ")
                if name not in self.keywords:
                    self.keywords.append(name)

        # ── 流式 ASR（Zipformer transducer INT8；无 joiner 时回退 Paraformer）──
        ep = dict(
            num_threads=int(s.get("num_threads", 2)),
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=float(s["asr"].get("rule1_silence", 2.4)),
            rule2_min_trailing_silence=float(s["asr"].get("rule2_silence", 1.2)),
            rule3_min_utterance_length=float(s["asr"].get("rule3_utt_len", 20.0)),
            provider=s.get("provider", "cpu"),
        )
        # 热词（智能家居高频词加权，缺失时静默跳过，不影响启动）
        # 注意：sherpa 热词仅在 modified_beam_search 解码下生效，greedy 会直接报错
        hw = s["asr"].get("hotwords_file")
        if hw:
            hw_path = _abspath(hw)
            if os.path.isfile(hw_path):
                ep["hotwords_file"] = hw_path
                ep["hotwords_score"] = float(s["asr"].get("hotwords_score", 2.0))
                ep["decoding_method"] = "modified_beam_search"
        joiner_path = os.path.join(asr_dir, "joiner.onnx")
        if os.path.isfile(joiner_path):
            self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=os.path.join(asr_dir, "tokens.txt"),
                encoder=os.path.join(asr_dir, "encoder.onnx"),
                decoder=os.path.join(asr_dir, "decoder.onnx"),
                joiner=joiner_path,
                **ep)
        else:
            self.recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
                tokens=os.path.join(asr_dir, "tokens.txt"),
                encoder=os.path.join(asr_dir, "encoder.onnx"),
                decoder=os.path.join(asr_dir, "decoder.onnx"),
                **ep)
        self.asr_stream = self.recognizer.create_stream()
        self.last_partial = ""

    def accept(self, pcm_float32: np.ndarray, *, enable_kws: bool = True,
               enable_asr: bool = True) -> list[tuple[str, str]]:
        """喂一帧 PCM，并按对话状态选择 KWS/ASR。

        ASR 在待唤醒、提示音、思考和 TTS 播放期间必须关闭，否则助手自己的
        声音会积累成下一轮用户输入。关闭时同时丢弃旧半句，重新开始监听时不会
        带入前一状态的残音。
        """
        events: list[tuple[str, str]] = []

        # KWS
        if enable_kws:
            self.kws_stream.accept_waveform(_SAMPLE_RATE, pcm_float32)
            while self.kws.is_ready(self.kws_stream):
                self.kws.decode_stream(self.kws_stream)
            kw = self.kws.get_result(self.kws_stream)  # Python 绑定直接返回关键词内部名
            if kw:
                events.append(("wake", kw.replace("_", " ")))  # Hey_Bota → "Hey Bota"
                # KeywordSpotter 只有 reset_stream（1.13 起），没有 OnlineRecognizer 那样的
                # reset：写错会在第一次命中唤醒词时抛 AttributeError，被音频回调吞掉。
                self.kws.reset_stream(self.kws_stream)

        # ASR（端点检测自动切句）
        if not enable_asr:
            if self.last_partial:
                self.reset_asr()
            return events
        self.asr_stream.accept_waveform(_SAMPLE_RATE, pcm_float32)
        while self.recognizer.is_ready(self.asr_stream):
            self.recognizer.decode_stream(self.asr_stream)
        # 1.13 Python 绑定：get_result 直接返回识别文本字符串
        text = self.recognizer.get_result(self.asr_stream).strip()
        if text and text != self.last_partial:
            self.last_partial = text
            events.append(("partial", text))
        if self.recognizer.is_endpoint(self.asr_stream):
            final = self.recognizer.get_result(self.asr_stream).strip()
            self.recognizer.reset(self.asr_stream)
            self.last_partial = ""
            if final:
                events.append(("final", final))
        return events

    def finalize_asr(self) -> str:
        """在最长发言保护触发时提交当前识别文本并重置流。"""
        text = self.recognizer.get_result(self.asr_stream).strip()
        self.recognizer.reset(self.asr_stream)
        self.last_partial = ""
        return text

    def reset_asr(self):
        """丢弃当前 ASR 半句（处理指令期间误录入时调用）。"""
        self.recognizer.reset(self.asr_stream)
        self.last_partial = ""


def _abspath(p: str) -> str:
    if os.path.isabs(p):
        return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), p)


def check_models(cfg: dict) -> list[str]:
    """返回缺失文件列表（空列表=齐全）。"""
    s = cfg["sherpa"]
    need = []
    kws_dir = _abspath(s["kws"]["model_dir"])
    for f in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"):
        if not os.path.isfile(os.path.join(kws_dir, f)):
            need.append(f"kws/{f}")
    if not os.path.isfile(_abspath(s["kws"]["keywords_file"])):
        need.append("kws/keywords.txt")
    asr_dir = _abspath(s["asr"]["model_dir"])
    # transducer（zipformer）需要 joiner；paraformer 只有 encoder+decoder
    asr_files = (("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt")
                 if os.path.isfile(os.path.join(asr_dir, "joiner.onnx"))
                 else ("encoder.onnx", "decoder.onnx", "tokens.txt"))
    for f in asr_files:
        if not os.path.isfile(os.path.join(asr_dir, f)):
            need.append(f"asr/{f}")
    tts_dir = _abspath(s["tts"]["model_dir"])
    for f in ("model.onnx", "tokens.txt"):
        if not os.path.isfile(os.path.join(tts_dir, f)):
            need.append(f"tts/{f}")
    return need
