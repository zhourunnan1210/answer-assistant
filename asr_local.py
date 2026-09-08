# -*- coding: utf-8 -*-
"""本地语音识别：阿里通义开源 SenseVoice（经 sherpa-onnx 推理，ONNX int8 量化）。

完全离线、免 Key、零网络延迟：实测模型加载约 1.2s（仅首次），
3 秒音频推理约 0.1s，远快于云端免费档（冷启动可达 24s+）。

模型文件随安装包附带，位于 exe/脚本同目录的 models/sense-voice/ 下：
  - model.int8.onnx（约 228MB）
  - tokens.txt
"""
import io
import os
import re
import sys
import threading
import wave

MODEL_DIR = os.path.join("models", "sense-voice")
MODEL_FILE = "model.int8.onnx"
TOKENS_FILE = "tokens.txt"

_lock = threading.Lock()
_recognizer = None

# SenseVoice 输出的元信息标记，如 <|zh|><|HAPPY|><|Speech|><|withitn|>
_META_RE = re.compile(r"<\|[^|]+\|>")


class LocalAsrError(Exception):
    pass


def model_dir() -> str:
    """模型目录的绝对路径（exe 冻结时取 exe 同目录）。"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, MODEL_DIR)


def model_ready() -> bool:
    d = model_dir()
    return (os.path.isfile(os.path.join(d, MODEL_FILE))
            and os.path.isfile(os.path.join(d, TOKENS_FILE)))


def _get_recognizer():
    """懒加载并全局缓存识别器（加载约 1.2s，只发生一次）。"""
    global _recognizer
    with _lock:
        if _recognizer is None:
            if not model_ready():
                raise LocalAsrError(
                    "未找到本地语音模型（" + model_dir() + "），"
                    "请确认安装目录下存在 models/sense-voice，"
                    "或在设置中把语音识别来源切换为云端 API。")
            import sherpa_onnx
            d = model_dir()
            _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                model=os.path.join(d, MODEL_FILE),
                tokens=os.path.join(d, TOKENS_FILE),
                num_threads=4, use_itn=True, debug=False)
    return _recognizer


def transcribe_local(wav_bytes: bytes) -> str:
    """识别 16kHz 单声道 16bit wav 字节，返回文本（已剥离元信息标记）。"""
    import numpy as np
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        if w.getframerate() != 16000 or w.getnchannels() != 1:
            raise LocalAsrError("音频格式不符：需要 16kHz 单声道 wav")
        pcm = w.readframes(w.getnframes())
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    if len(samples) == 0:
        return ""
    rec = _get_recognizer()
    with _lock:  # 解码期间串行化，避免并发调用同一识别器
        stream = rec.create_stream()
        stream.accept_waveform(16000, samples)
        rec.decode_stream(stream)
        text = stream.result.text
    return _META_RE.sub("", text).strip()


def warmup():
    """预加载模型（可选），避免首次识别时卡顿。"""
    _get_recognizer()
