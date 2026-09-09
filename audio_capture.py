# -*- coding: utf-8 -*-
"""系统音频输出回环采集（WASAPI loopback）+ 静音断句。

采集扬声器/耳机里播放的声音（如会议中对方的讲话），按静音自动切成
一句一句的语音，转成 16kHz 单声道 wav 字节，供语音识别接口使用。
只采集系统输出，不采集麦克风。
"""
import struct
import threading

import numpy as np

CAPTURE_RATE = 48000   # 回环采集采样率（WASAPI 混音格式常见值）
TARGET_RATE = 16000    # Whisper/SenseVoice 等 ASR 的标准输入
BLOCK_MS = 100         # 每次读取 100ms
SILENCE_RMS = 0.008    # 静音能量阈值（float32 RMS）
SILENCE_HOLD = 0.6     # 连续静音 0.6s 视为一句结束（缩短以加快响应）
MIN_UTTERANCE = 0.6    # 短于 0.6s 的声音丢弃（咳嗽/敲桌等杂音）
MAX_UTTERANCE = 8.0    # 单段上限：短句识别更快，避免长音频排队


def pcm_to_wav(pcm_int16: bytes, rate: int = TARGET_RATE) -> bytes:
    """16bit 单声道 PCM 裸数据 -> 完整 wav 文件字节。"""
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm_int16), b"WAVE", b"fmt ",
        16, 1, 1, rate, rate * 2, 2, 16, b"data", len(pcm_int16))
    return header + pcm_int16


def merge_wavs(wavs: list) -> bytes:
    """把若干段 wav（本模块生成的 16kHz 单声道）拼接为一段。"""
    return pcm_to_wav(b"".join(w[44:] for w in wavs))


def test_tone_wav(duration: float = 0.8, freq: float = 440.0) -> bytes:
    """生成一段 16kHz 正弦提示音（440Hz「嘟」声），用于 ASR 连通性测试。"""
    t = np.arange(int(TARGET_RATE * duration)) / TARGET_RATE
    pcm = (np.sin(2 * np.pi * freq * t) * 12000).astype(np.int16).tobytes()
    return pcm_to_wav(pcm)


class _VadCapture(threading.Thread):
    """后台采集线程基类：静音断句，每切出一句完整语音就回调
    on_utterance(wav_bytes)；异常回调 on_error(msg)。
    子类实现 _open() 返回 (设备, 声道数)。"""

    def __init__(self, on_utterance, on_error=None):
        super().__init__(daemon=True)
        self.on_utterance = on_utterance
        self.on_error = on_error
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _open(self):
        raise NotImplementedError

    def run(self):
        try:
            self._loop()
        except Exception as exc:  # noqa: BLE001
            if self.on_error and not self._stop_event.is_set():
                self.on_error(str(exc))

    def _loop(self):
        device, channels = self._open()
        block = int(CAPTURE_RATE * BLOCK_MS / 1000)
        speech = []      # 当前语音段的音频块
        silence_t = 0.0  # 已连续静音时长（秒）
        with device.recorder(samplerate=CAPTURE_RATE, channels=channels,
                             blocksize=block) as rec:
            while not self._stop_event.is_set():
                data = rec.record(numframes=block)  # float32 (n, ch)
                mono = data.mean(axis=1)
                rms = float(np.sqrt(np.mean(mono ** 2)) + 1e-12)
                if rms >= SILENCE_RMS:
                    speech.append(mono)
                    silence_t = 0.0
                elif speech:
                    speech.append(mono)  # 保留尾音，避免切掉句尾
                    silence_t += BLOCK_MS / 1000
                if not speech:
                    continue
                dur = len(speech) * BLOCK_MS / 1000
                if silence_t >= SILENCE_HOLD:
                    if dur >= MIN_UTTERANCE:
                        self._emit(np.concatenate(speech))
                    speech, silence_t = [], 0.0
                elif dur >= MAX_UTTERANCE:
                    self._emit(np.concatenate(speech))
                    speech, silence_t = [], 0.0
        # 停止时把未说完的一段也吐出来
        if speech and len(speech) * BLOCK_MS / 1000 >= MIN_UTTERANCE:
            self._emit(np.concatenate(speech))

    def _emit(self, mono_f32):
        # 48k -> 16k 线性插值重采样，转 16bit PCM，加 wav 头
        n_out = int(len(mono_f32) * TARGET_RATE / CAPTURE_RATE)
        idx = np.linspace(0, len(mono_f32) - 1, n_out)
        res = np.interp(idx, np.arange(len(mono_f32)), mono_f32)
        pcm = (np.clip(res, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
        self.on_utterance(pcm_to_wav(pcm))


class LoopbackCapture(_VadCapture):
    """采集系统输出（扬声器/耳机里播放的声音，如会议中对方的讲话）。"""

    def _open(self):
        import soundcard as sc
        speaker = sc.default_speaker()
        mic = sc.get_microphone(speaker.name, include_loopback=True)
        return mic, 2


class MicCapture(_VadCapture):
    """采集麦克风（面试场景中候选人自己的回答），用于对话上下文跟踪。"""

    def _open(self):
        import soundcard as sc
        return sc.default_microphone(), 1
