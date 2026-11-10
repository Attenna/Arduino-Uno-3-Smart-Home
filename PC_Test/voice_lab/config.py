"""Configuration loading and small path helpers for the voice lab."""
from __future__ import annotations

import copy
import os
from typing import Any, Optional

import yaml

VOICE_LAB_DIR = os.path.dirname(os.path.abspath(__file__))
PC_TEST_DIR = os.path.dirname(VOICE_LAB_DIR)
REPO_DIR = os.path.dirname(PC_TEST_DIR)

DEFAULT_CONFIG: dict[str, Any] = {
    "asr": {
        "backend": "sherpa",
        "sherpa": {
            "model_dir": "models/sherpa/asr_zh",
            "num_threads": 4,
            "rule1_silence": 2.4,
            "rule2_silence": 1.2,
            "rule3_utt_len": 20.0,
            "hotwords_file": "",
            "hotwords_score": 2.0,
            "max_active_paths": 4,
        },
        "whisper": {
            "model": "small",
            "download_root": "models/whisper",
            "device": "cpu",
            "compute_type": "float32",
            "language": "zh",
            "beam_size": 1,
            "fp16": False,
        },
    },
    "llm": {
        "backend": "hybrid",
        "history_rounds": 3,
        "max_tool_calls": 4,
        "max_tokens": 128,
        "temperature": 0.2,
        "llama_cpp": {
            "model_path": "models/qwen/qwen2.5-3b-instruct-q4_k_m.gguf",
            "n_ctx": 4096,
            "n_threads": 12,
            "n_batch": 512,
            "n_gpu_layers": 0,
            "verbose": False,
        },
        "openai": {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "Qwen/Qwen3.5-4B",
            "api_key": "",
            "api_key_file": "llm_key.txt",
            "timeout_s": 30.0,
            "extra_body": {"enable_thinking": False},
        },
    },
    "tts": {
        "backend": "edge",
        "cache_dir": "voice_lab/output/tts_cache",
        "edge": {
            "voice": "zh-CN-XiaoxiaoNeural",
            "rate": "+0%",
            "volume": "+0%",
        },
        "sherpa": {
            "model_dir": "models/sherpa/tts",
            "speaker_id": 0,
            "speed": 1.0,
            "num_threads": 2,
        },
        "cosyvoice": {
            "base_url": "https://api.siliconflow.cn/v1",
            "model": "FunAudioLLM/CosyVoice2-0.5B",
            "voice": "anna",
            "api_key": "",
            "api_key_file": "llm_key.txt",
            "response_format": "mp3",
            "timeout_s": 60.0,
        },
    },
    "dialog": {
        "system_prompt": (
            "你是智能家居语音助手。用户要求控制设备时必须调用工具，不要编造执行结果。"
            "回复口语化、简短，一次只说一两句；不要输出 JSON、工具名或思维过程。"
            "不确定意图时简短反问。"
        ),
        "followup_timeout": 8.0,
        "command_timeout": 8.0,
        "max_utterance_seconds": 15.0,
    },
    "wake": {
        "enabled": False,
        "kws": {
            "model_dir": "models/sherpa/kws",
            "keywords_file": "models/sherpa/kws/keywords.txt",
            "keywords_score": 1.5,
            "keywords_threshold": 0.25,
            "num_threads": 2,
        },
        "ack": "chirp",
        "chirp_freq": 880,
        "chirp_ms": 120,
        "command_timeout": 8.0,
        "followup_timeout": 8.0,
        "max_utterance_seconds": 15.0,
        # True barge-in needs AEC; keep false for the half-duplex demo.
        "barge_in": False,
    },
    "server": {"host": "127.0.0.1", "port": 8110},
    "audio": {
        "sample_rate": 16000,
        "channels": 1,
        "record_seconds": 6.0,
        "silence_seconds": 0.8,
        "energy_threshold": 0.012,
        "min_speech_seconds": 0.2,
    },
}


def _merge(base: dict, over: dict) -> None:
    for key, value in (over or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


def _resolve(value: str, base: str = PC_TEST_DIR) -> str:
    if not value:
        return value
    if os.path.isabs(value):
        return value
    return os.path.normpath(os.path.join(base, value))


def load_config(path: Optional[str] = None, overrides: Optional[dict] = None) -> dict[str, Any]:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            _merge(cfg, yaml.safe_load(handle) or {})
    if overrides:
        _merge(cfg, overrides)
    # Resolve file-system paths against PC_Test so the CLI works from any cwd.
    for key in ("model_dir", "download_root", "model_path", "cache_dir", "keywords_file"):
        for section in ("asr", "llm", "tts", "wake"):
            sub = cfg.get(section, {})
            if isinstance(sub.get(key), str):
                sub[key] = _resolve(sub[key])
            for name, child in sub.items():
                if isinstance(child, dict) and isinstance(child.get(key), str):
                    child[key] = _resolve(child[key])
    for env_name, path in (
        ("VOICE_LAB_ASR", ("asr", "backend")),
        ("VOICE_LAB_LLM", ("llm", "backend")),
        ("VOICE_LAB_TTS", ("tts", "backend")),
    ):
        if os.environ.get(env_name):
            cfg[path[0]][path[1]] = os.environ[env_name]
    return cfg


def read_api_key(section: dict[str, Any]) -> str:
    """Config value > LLM_API_KEY / SILICONFLOW_API_KEY > key file."""
    key = str(section.get("api_key") or "").strip()
    if key and key.lower() not in ("none", "null", ""):
        return key
    for env_name in ("LLM_API_KEY", "SILICONFLOW_API_KEY", "DASHSCOPE_API_KEY"):
        value = os.environ.get(env_name)
        if value:
            return value.strip()
    filename = section.get("api_key_file")
    if filename:
        path = _resolve(str(filename))
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        return line
    return ""


def default_config_path() -> str:
    local = os.path.join(VOICE_LAB_DIR, "config.local.yaml")
    if os.path.exists(local):
        return local
    return os.path.join(VOICE_LAB_DIR, "config.yaml")
