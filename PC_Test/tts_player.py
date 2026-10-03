"""tts_player.py — 流式 TTS 播放器（Sherpa-ONNX VITS 本地引擎）

把 LLM 流式输出的 token 按句切分，后台线程一边合成一边播放：
    LLM token → feed_token() 按句入队
                 ↓ (queue.Queue)
    worker 线程：sherpa-onnx VITS 本地合成 → sounddevice 同步播放

完全离线本地推理（可移植到香橙派），无外部 TTS 服务依赖。
第一句在后续句子还在生成时即可播放，做到"边生成边播"。

对外 API 与旧版（edge-tts）一致：speak/feed_token/flush/stop/wait_done/
is_busy/shutdown + list_input_devices()。
"""
import os
import queue
import re
import threading
from typing import Optional

import numpy as np
import sounddevice as sd

# 句末标点：中文 。！？ 和英文 !?.\n
_SENTENCE_END = re.compile(r"[。！？!??\n]+")
_STOP_SENTINEL = object()


class _Chirp:
    """唤醒提示音（队列项）：零合成延迟的正弦短音，比 TTS 说「在的」反馈更快。"""

    def __init__(self, freq: float = 880.0, ms: int = 120):
        self.freq = freq
        self.ms = ms


def _abspath(p: str) -> str:
    if os.path.isabs(p):
        return p
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), p)


class TtsPlayer:
    """流式 TTS 播放器（线程安全）。

    cfg 来自 voice_config.yaml 的 sherpa.tts 段；也接受旧参数 voice/rate/volume
    （voice/rate/volume 传了会被忽略，音色由 VITS 模型的 speaker_id 决定）。
    """

    def __init__(self, cfg: Optional[dict] = None,
                 voice: str = "", rate: str = "", volume: str = ""):
        import sherpa_onnx
        cfg = cfg or {}
        tts_dir = _abspath(cfg.get("model_dir", "models/sherpa/tts"))
        sid = int(cfg.get("speaker_id", 0))
        self.speed = float(cfg.get("speed", 1.0))
        self._sid = sid

        model = os.path.join(tts_dir, "model.onnx")
        tokens = os.path.join(tts_dir, "tokens.txt")
        if not os.path.isfile(model) or not os.path.isfile(tokens):
            raise FileNotFoundError(
                f"TTS 模型未找到: {tts_dir}（需 model.onnx + tokens.txt）\n"
                f"  请先运行: py -3.13 download_sherpa_models.py --tts-only")

        vits = sherpa_onnx.OfflineTtsVitsModelConfig(
            model=model,
            tokens=tokens,
            lexicon=os.path.join(tts_dir, "lexicon.txt")
                    if os.path.isfile(os.path.join(tts_dir, "lexicon.txt")) else "",
            dict_dir=os.path.join(tts_dir, "dict")
                     if os.path.isdir(os.path.join(tts_dir, "dict")) else "",
        )
        tts_model = sherpa_onnx.OfflineTtsModelConfig(
            vits=vits, num_threads=int(cfg.get("num_threads", 2)),
            provider=cfg.get("provider", "cpu"), debug=False)
        tts_cfg = sherpa_onnx.OfflineTtsConfig(model=tts_model, max_num_sentences=2)
        if not tts_cfg.validate():
            raise ValueError(f"TTS 配置校验失败: {tts_dir}")
        self.tts = sherpa_onnx.OfflineTts(tts_cfg)
        self.sample_rate = self.tts.sample_rate
        try:
            self.output_available = any(
                int(device.get("max_output_channels", 0)) > 0
                for device in sd.query_devices())
        except Exception:
            self.output_available = False
        self.output_status = ("扬声器可用" if self.output_available else
                              "未检测到播放设备，回复仅显示在 UI")

        self._q: "queue.Queue[object]" = queue.Queue()
        self._buf: list[str] = []        # 跨 token 的待切分缓冲
        self._cancel = threading.Event()  # 打断当前句
        self._playing = threading.Event()  # 正在播放音频（供外部做回声抑制）
        self._thread = threading.Thread(target=self._run, daemon=True, name="tts-worker")
        self._thread.start()

    def is_busy(self) -> bool:
        """是否正在播放音频（用于唤醒防回声）。"""
        return self._playing.is_set() or not self._q.empty()

    # ── 对外 API ──────────────────────────────────────────────

    def feed_token(self, token: str) -> None:
        """接收 LLM 流式 token，累积按句切分入队。"""
        if not token:
            return
        self._buf.append(token)
        text = "".join(self._buf)
        last = None
        for m in _SENTENCE_END.finditer(text):
            last = m
        if last is not None:
            sentence = text[:last.end()].strip()
            self._buf = [text[last.end():]]
            if sentence:
                self._q.put(sentence)

    def speak(self, text: str) -> None:
        """直接入队一整句（不切分）。"""
        if text and text.strip():
            self._q.put(text.strip())

    def chirp(self, freq: float = 880.0, ms: int = 120) -> None:
        """入队一个唤醒提示音（滴声），排在语音前串行播放。"""
        self._q.put(_Chirp(freq, ms))

    def flush(self) -> None:
        """把缓冲里残留的尾巴入队（LLM 结束时调用）。"""
        rest = "".join(self._buf).strip()
        self._buf = []
        if rest:
            self._q.put(rest)

    def stop(self) -> None:
        """打断：清空队列 + 中止当前播放。"""
        self._cancel.set()
        while True:
            try:
                self._q.get_nowait()
                self._q.task_done()
            except queue.Empty:
                break
        try:
            sd.stop()
        except Exception:
            pass

    # 兼容旧代码里的别名
    interrupt = stop

    def wait_done(self, timeout: Optional[float] = None) -> bool:
        """阻塞直到队列处理完。"""
        self._q.join()
        return True

    def shutdown(self) -> None:
        self.flush()
        self._q.put(_STOP_SENTINEL)
        self._thread.join(timeout=2)

    # ── 内部 ──────────────────────────────────────────────────

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is _STOP_SENTINEL:
                self._q.task_done()
                break
            try:
                if isinstance(item, _Chirp):
                    self._play_chirp(item)
                else:
                    self._play_sentence(str(item))
            except Exception as e:
                print(f"[TTS] 播放失败跳过（{e}）")
            finally:
                self._cancel.clear()
                self._q.task_done()

    def _play_chirp(self, c: "_Chirp") -> None:
        import numpy as np
        if self._cancel.is_set() or not self.output_available:
            return
        rate = 44100
        n = int(rate * c.ms / 1000)
        t = np.arange(n, dtype=np.float32) / rate
        wave = 0.25 * np.sin(2 * np.pi * c.freq * t)
        # 首尾各 6ms 淡入淡出，避免爆音"啪"声
        fade = min(int(rate * 0.006), n // 2)
        if fade > 0:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            wave[:fade] *= ramp
            wave[-fade:] *= ramp[::-1]
        self._playing.set()
        try:
            sd.play(wave, samplerate=rate, blocking=True)
        except Exception as e:
            print(f"[TTS] 提示音失败: {e}")
        finally:
            self._playing.clear()

    def _play_sentence(self, text: str) -> None:
        if self._cancel.is_set() or not self.output_available:
            return
        # 1) sherpa VITS 本地合成（同步调用，3B 级句子通常 <0.5s）
        try:
            audio = self.tts.generate(text, sid=self._sid, speed=self.speed)
        except Exception as e:
            print(f"[TTS] 合成失败: {e}")
            return
        if self._cancel.is_set() or not audio.samples:
            return
        # 2) sounddevice 同步播放（blocking；stop() 调 sd.stop() 解除）
        self._playing.set()
        try:
            arr = np.array(audio.samples, dtype=np.float32)
            sd.play(arr, samplerate=audio.sample_rate, blocking=True)
        except Exception as e:
            print(f"[TTS] 播放失败: {e}")
        finally:
            self._playing.clear()


def list_input_devices() -> list[tuple[int, str]]:
    """列出可用输入设备（麦克风），供 --list-mic 使用。"""
    devs = sd.query_devices()
    out = []
    for i, d in enumerate(devs):
        if d["max_input_channels"] > 0:
            out.append((i, d["name"]))
    return out
