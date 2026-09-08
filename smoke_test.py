# -*- coding: utf-8 -*-
"""离屏冒烟测试：验证模块导入、配置读写、UI 构造。"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

import config
import llm
import main as app_main

# 1. 配置读写
cfg = config.AppConfig.load()
cfg.set("model", "test-model")
cfg.save()
cfg2 = config.AppConfig.load()
assert cfg2.model == "test-model", "配置持久化失败"
assert cfg2.provider in ("openai", "anthropic")
print("✓ 配置读写正常 ->", config.config_path())

# 2. UI 构造
app = QApplication(sys.argv)
win = app_main.MainWindow()
win.show()
assert win.ask_btn and win.region_btn
assert win.monitor_btn is None and win.auto_btn is None, "监控/自动按钮应已下线"
assert llm.DEFAULT_PROMPT
print("✓ 主窗口构造正常（监控/自动按钮已隐藏）")

# 3. 设置对话框构造
dlg = app_main.SettingsDialog(win.cfg, win)
snap = dlg._snapshot()
assert "provider" in snap and "monitor_interval_ms" in snap
assert "thinking" in snap and isinstance(snap["thinking"], bool), "思考模式字段缺失"
assert "hotkey" in snap and snap["hotkey"] in app_main.HOTKEYS, "快捷键字段缺失"
assert "font_size" in snap and 10 <= snap["font_size"] <= 28, "字号字段缺失"
assert hasattr(dlg, "fetch_btn") and hasattr(dlg, "thinking")
assert hasattr(dlg, "preset") and dlg.preset.count() >= 6, "供应商预设缺失"
# 预设联动：选中 DeepSeek 预设应自动填入 base_url
dlg.preset.setCurrentIndex(3)
dlg._apply_preset(3)
assert "deepseek" in dlg.base_url.text(), dlg.base_url.text()
print("✓ 设置对话框正常，快照字段完整（含思考模式/供应商预设）")

# 3b. 我的预设：保存/载入
dlg.cfg.data.setdefault("profiles", {})["测试预设"] = {
    "provider": "openai", "base_url": "https://x.test/v1",
    "api_key": "k123", "model": "m-test", "thinking": False}
dlg._reload_profiles(select="测试预设")
dlg._load_profile(1)
assert dlg.base_url.text() == "https://x.test/v1", dlg.base_url.text()
assert dlg.model.currentText() == "m-test"
assert dlg.api_key.text() == "k123" and dlg.thinking.isChecked() is False
print("✓ 我的预设保存/载入正常")

# 4. 新接口签名
assert callable(llm.fetch_models)
import inspect
assert "thinking" in inspect.signature(llm._openai_chat).parameters
assert "thinking" in inspect.signature(llm._anthropic_chat).parameters
print("✓ fetch_models / 思考模式参数就位")

# 5. 自动作答解析函数
d = app_main.parse_auto_answer('{"answer":"B","answer_box":[0.1,0.2,0.9,0.3],"next_box":null}')
assert d and d["answer_box"] == [0.1, 0.2, 0.9, 0.3] and d["next_box"] is None
d2 = app_main.parse_auto_answer('前言 {"answer":"A","answer_box":[50,150,950,230]} 后缀')
assert d2 and abs(d2["answer_box"][0] - 0.05) < 1e-6, "0~1000 坐标系兼容失败"
assert app_main.parse_auto_answer("没有JSON") is None
pt = app_main.box_center([0, 0, 1, 0.5], {"x": 100, "y": 200, "w": 400, "h": 300})
assert pt == (300, 275), pt
assert hasattr(win, "auto_btn") and hasattr(win, "_auto_wait_change")
assert llm.AUTO_PROMPT
print("✓ 自动作答解析/坐标/点击链路就位")

# 6. 标题栏预设下拉
assert hasattr(win, "profile_bar")
win.cfg.data["profiles"] = {"P1": {"provider": "openai", "base_url": "https://x",
                                   "api_key": "k", "model": "m", "thinking": True}}
win.cfg.data.update({"provider": "openai", "base_url": "https://x",
                     "api_key": "k", "model": "m", "thinking": True})
assert win._current_profile_name() == "P1"
win._reload_profile_bar()
assert win.profile_bar.count() == 1 and win.profile_bar.currentText() == "P1"
win.cfg.data["model"] = "other"
assert win._current_profile_name() is None
assert hasattr(win, "tray") and hasattr(win, "_minimize_to_tray"), "托盘功能缺失"
assert hasattr(win, "_bring_to_front"), "窗口提到最前功能缺失"
assert app_main.WDA_MONITOR == 0x1 and app_main.WDA_EXCLUDEFROMCAPTURE == 0x11
print("✓ 标题栏预设切换/匹配逻辑就位")

# 4. 指纹/差异函数（用空 pixmap 不行，跳过像素级，仅验证函数存在）
assert callable(app_main.diff_ratio)

# 7. 全局快捷键：四个热键 + 识别热键选项里不再含 Ctrl+Alt+S
assert "Ctrl+Alt+S" not in app_main.HOTKEYS, "Ctrl+Alt+S 已用作切换预设，不应再是识别热键选项"
assert len(win._hotkey_filter.handlers) == 4, win._hotkey_filter.handlers
assert win._hotkey_filter.handlers[app_main.MainWindow.HOTKEY_ID_ASK] == win._on_hotkey
assert win._hotkey_filter.handlers[app_main.MainWindow.HOTKEY_ID_CYCLE] == win._cycle_profile
assert win._hotkey_filter.handlers[app_main.MainWindow.HOTKEY_ID_CLEAR] == win._clear_answer
assert win._hotkey_filter.handlers[app_main.MainWindow.HOTKEY_ID_QA] == win._qa_answer
hint = win.answer.toPlainText()
assert "Ctrl+Alt+S" in hint and "Ctrl+Alt+C" in hint, "提示区缺少快捷键说明"
assert "Ctrl+Alt+W" in hint, "提示区缺少问答快捷键说明"
print("✓ 快捷键分发/提示区说明就位（多行以灰色正文渲染，绕过 Qt placeholder 单行限制）")

# 8. 问答助手：UI、配置、接口、音频模块
assert hasattr(win, "qa_btn") and hasattr(win, "qa_answer_btn")
assert callable(llm.transcribe_audio) and callable(llm.ask_text)
assert callable(llm.test_asr), "ASR 连通性测试缺失"
assert "prompt" in win.PROFILE_KEYS and "qa_prompt" in win.PROFILE_KEYS, \
    "预设应包含两种提示词"
assert hasattr(dlg, "nav") and hasattr(dlg, "pages"), "设置页卡片切换缺失"
assert hasattr(dlg, "asr_test_btn"), "ASR 测试按钮缺失"
assert "qa_prompt" in cfg2.data and "asr_model" in cfg2.data
assert "asr_use_same_key" in cfg2.data and "asr_base_url" in cfg2.data
import audio_capture
w1 = audio_capture.pcm_to_wav(b"\x00\x01" * 100)
assert w1[:4] == b"RIFF" and audio_capture.merge_wavs([w1, w1])[44:] == w1[44:] * 2
snap2 = dlg._snapshot()
assert "asr_api_key" in snap2 and "qa_prompt" in snap2, "设置快照缺少问答助手字段"
print("✓ 问答助手链路就位（采集/识别/问答/配置）")

# 9. 本地语音识别：SenseVoice + sherpa-onnx 离线链路
import asr_local
assert "asr_source" in cfg2.data, "配置缺少 asr_source 字段"
assert cfg2.data["asr_source"] in ("local", "cloud")
snap3 = dlg._snapshot()
assert "asr_source" in snap3, "设置快照缺少 asr_source"
assert hasattr(dlg, "asr_src_local") and hasattr(dlg, "asr_src_cloud")
assert hasattr(dlg, "asr_local_status"), "本地模型状态标签缺失"
assert asr_local.model_ready(), "本地模型文件缺失：" + asr_local.model_dir()
assert callable(llm.asr_use_local)
# 分流：local 走 sherpa-onnx 离线推理，cloud 走 HTTP（此处验证本地路径）
local_cfg = dict(cfg2.data)
local_cfg["asr_source"] = "local"
import time as _t
_t0 = _t.time()
txt = llm.transcribe_audio(local_cfg, audio_capture.test_tone_wav())
_elapsed = _t.time() - _t0
assert isinstance(txt, str), "本地识别应返回字符串"
assert _elapsed < 10, f"本地识别过慢：{_elapsed:.1f}s"
msg = llm.test_asr(local_cfg)
assert "本地模型就绪" in msg, msg
print(f"✓ 本地语音识别链路就位（测试音识别耗时 {_elapsed:.2f}s）")
print("✓ 全部冒烟测试通过")

QTimer.singleShot(100, app.quit)
app.exec()
