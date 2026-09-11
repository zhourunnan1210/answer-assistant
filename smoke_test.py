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
import tempfile
os.environ["PROFILE_DIR"] = tempfile.mkdtemp()  # 资料库指向临时目录，避免污染真实数据
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

# 10. 面试辅助：文档解析、配置字段、ask_interview、UI 开关
import docparse
import tempfile
_tmp = tempfile.mkdtemp()
_p_txt = os.path.join(_tmp, "简历.txt")
with open(_p_txt, "w", encoding="utf-8") as _f:
    _f.write("# 张三\n\n**3 年** Python 开发经验\n\n\n主导 推荐系统 项目")
_t = docparse.extract_text(_p_txt)
assert "张三" in _t and "3 年" in _t and "\n\n\n" not in _t, repr(_t)  # 空白压缩、换行归一
_p_md = os.path.join(_tmp, "r.md")
with open(_p_md, "w", encoding="utf-8") as _f:
    _f.write("## 经历\n- **鹅厂** 后端开发\n")
assert "**" not in docparse.extract_text(_p_md), "Markdown 标记应被去除"
try:
    docparse.extract_text(os.path.join(_tmp, "x.exe"))
    raise SystemExit("不支持的格式应抛错")
except docparse.DocParseError:
    pass
assert "interview_prompt" in cfg2.data and "resume_text" in cfg2.data
assert "interview_prompt" in snap3 or "interview_prompt" in dlg._snapshot()
assert "interview_prompt" in win.PROFILE_KEYS, "预设应包含面试提示词"
assert callable(llm.ask_interview)
try:
    llm.ask_interview({"api_key": "k", "model": "m"}, "问题")
    raise SystemExit("无资料库时应抛错")
except llm.LlmError as _e:
    assert "资料库" in str(_e)
assert hasattr(win, "interview_btn") and hasattr(dlg, "interview_prompt")
assert hasattr(dlg, "fixed_editor") and hasattr(dlg, "flex_list"), "资料库 UI 缺失"
assert hasattr(dlg, "_upload_raw") and hasattr(dlg, "_gen_fixed")
assert hasattr(dlg, "_gen_flex") and hasattr(dlg, "_edit_flex")
# 未加载简历时面试开关应被拒绝
win.cfg.data["resume_text"] = ""
win.interview_btn.setChecked(True)
assert not win.interview_btn.isChecked(), "无简历时面试模式不应开启"
win.cfg.data["resume_text"] = "张三，3 年经验"
win.interview_btn.setChecked(True)
assert win.interview_btn.isChecked() and win.qa_btn.isChecked(), \
    "面试模式应自动带动问答监听开启"
win.interview_btn.setChecked(False)
win.qa_btn.setChecked(False)
win.cfg.data["resume_text"] = ""
print("✓ 面试辅助链路就位（文档解析/简历配置/UI 联动）")

# 11. 沉浸式模式：开关、联动条件、收缩/恢复几何
assert "immersive_mode" in cfg2.data and cfg2.data["immersive_mode"] is False
snap4 = dlg._snapshot()
assert "immersive_mode" in snap4 and isinstance(snap4["immersive_mode"], bool)
assert hasattr(dlg, "immersive"), "通用页缺少沉浸式开关"
assert "immersive_mode" not in win.PROFILE_KEYS, "沉浸式开关不应随预设变化"
assert hasattr(win, "_immersive_timer") and hasattr(win, "_set_immersive_ui")
win.cfg.data["immersive_mode"] = True
assert not win._immersive_engaged(), "未开问答/面试时不应生效"
win.qa_btn.setChecked(True)
assert win._immersive_engaged()
win._immersive_timer.stop()  # 手动测试收缩/恢复，避免轮询干扰断言
win.show()
app.processEvents()
geo0 = win.geometry()
win._set_immersive_ui(False)
app.processEvents()
assert win._immersive_hidden
assert not win.ask_btn.isVisible() and not win.profile_bar.isVisible()
assert not win.qa_answer_btn.isVisible()  # 问答按钮也随外壳隐藏
assert win.answer.isVisible()
g = win.geometry()
assert abs(g.width() - win.answer.width()) < 60 and g.height() < geo0.height()
win._set_immersive_ui(True)
app.processEvents()
assert not win._immersive_hidden and win.ask_btn.isVisible()
assert win.geometry().size() == geo0.size(), "恢复后窗口尺寸应一致"
assert win.qa_answer_btn.isVisible(), "问答模式下恢复时回答按钮应可见"
win.qa_btn.setChecked(False)
assert not win._immersive_engaged() and not win._immersive_timer.isActive()
assert not win._immersive_hidden, "关闭问答后应恢复完整 UI"
win.cfg.data["immersive_mode"] = False
print("✓ 沉浸式模式就位（联动/收缩/恢复几何正确）")

# 12. 区域背景透明度：配置字段、快照、样式参数化
assert "ui_bg_opacity" in cfg2.data and "answer_bg_opacity" in cfg2.data
snap5 = dlg._snapshot()
assert "ui_bg_opacity" in snap5 and "answer_bg_opacity" in snap5
assert hasattr(dlg, "ui_bg") and hasattr(dlg, "answer_bg"), "通用页缺少区域透明度滑块"
assert "ui_bg_opacity" not in win.PROFILE_KEYS
assert "answer_bg_opacity" not in win.PROFILE_KEYS, "区域透明度不应随预设变化"
win.cfg.data["ui_bg_opacity"] = 0.5
win._apply_panel_style()
assert "rgba(24, 27, 34, 128)" in win.styleSheet(), "面板背景透明度未生效"
win.cfg.data["answer_bg_opacity"] = 0.4
win._apply_answer_style()
assert "rgba(255, 255, 255, 102)" in win.answer.styleSheet(), "答案区背景透明度未生效"
win.cfg.data["ui_bg_opacity"] = 0.80
win.cfg.data["answer_bg_opacity"] = 0.05
win._apply_panel_style()
win._apply_answer_style()
print("✓ 区域背景透明度就位（UI 区/答案区独立，且不入预设）")

# 13. 个人资料库：CRUD、检索、上下文组装、双通道采集
import profile_store as ps
ps.save_fixed("# 个人介绍\n张三，3 年 Python 后端")
assert ps.load_fixed().startswith("# 个人介绍")
_docs = [
    {"id": 1, "title": "推荐系统项目技术细节", "keywords": ["推荐系统", "召回", "排序"],
     "content": "负责召回层优化，QPS 提升 40%"},
    {"id": 2, "title": "订单系统高并发改造", "keywords": ["订单", "高并发", "秒杀"],
     "content": "引入消息队列削峰，扛住 10w QPS"},
]
ps.save_flex(_docs)
assert len(ps.load_flex()) == 2
assert "推荐系统" in ps.flex_index(_docs)
_hits = ps.retrieve("讲讲你在推荐系统里做召回遇到什么问题", _docs)
assert _hits and _hits[0]["id"] == 1, _hits
assert ps.retrieve("今天天气怎么样", []) == []
# 原始资料
_raw_src = os.path.join(_tmp, "项目说明.txt")
with open(_raw_src, "w", encoding="utf-8") as _f:
    _f.write("推荐系统项目：负责召回与排序模块")
ps.add_raw(_raw_src)
assert "项目说明.txt" in ps.list_raw()
_raw_texts = ps.read_raw_texts()
assert _raw_texts and "召回" in _raw_texts[0][1]
ps.clear_raw()
assert ps.list_raw() == []
# 上下文组装：固定文稿 + 索引 + 命中专题 + 对话记录 + 问题
content = llm.build_interview_content(
    {"api_key": "k", "model": "m"}, "召回层是怎么优化的？",
    convo="面试官：介绍下推荐系统项目\n我：我负责召回层")
assert "【固定文稿】" in content and "【专题资料索引】" in content
assert "QPS 提升 40%" in content, "命中的专题应注入全文"
assert "面试官：介绍下推荐系统项目" in content
assert "【面试官最新讲话】" in content
# 超长截断
ps.save_fixed("长" * (ps.FIXED_MAX_CHARS + 2000))
_c2 = llm.build_interview_content({"api_key": "k", "model": "m"}, "无关问题 xyz")
assert "长" * ps.FIXED_MAX_CHARS in _c2
assert "长" * (ps.FIXED_MAX_CHARS + 1) not in _c2  # 超出上限部分被截断
assert "长" * (ps.FIXED_MAX_CHARS + 1) not in _c2, "固定文稿应按上限截断"
# 旧版简历字段回退兼容
ps.save_fixed("")
_c3 = llm.build_interview_content(
    {"api_key": "k", "model": "m", "resume_text": "旧版简历内容"}, "问题")
assert "旧版简历内容" in _c3
# 文稿 JSON 解析
_parsed = llm._parse_docs_json('```json\n[{"title":"t","content":"c"}]\n```')
assert _parsed and _parsed[0]["title"] == "t"
assert llm._parse_docs_json("没有JSON") == []
# 双通道采集类
assert hasattr(audio_capture, "MicCapture") and hasattr(audio_capture, "_VadCapture")
assert issubclass(audio_capture.MicCapture, audio_capture._VadCapture)
assert issubclass(audio_capture.LoopbackCapture, audio_capture._VadCapture)
# 主窗口双通道接线
assert hasattr(win, "_mic_bridge") and hasattr(win, "_on_mic_utterance")
assert hasattr(win, "_convo") and hasattr(win, "_trim_convo")
win._convo = ["x" * 2000] * 3
win._trim_convo()
assert sum(len(x) for x in win._convo) <= ps.CONVO_MAX_CHARS
print("✓ 资料库/检索/上下文组装/双通道就位")

# 14. Markdown 编辑器窗口：视图切换、meta、渲染
ed = app_main.MarkdownEditorDialog("**粗体** 内容", dlg, show_meta=True,
                                   meta=("标题一", "召回、排序"),
                                   start_mode="split")
assert ed.text() == "**粗体** 内容"
t, kws = ed.meta_values()
assert t == "标题一" and kws == ["召回", "排序"], (t, kws)
ed._set_mode("preview")
assert ed.editor.isHidden() and not ed.preview.isHidden()
ed._set_mode("edit")
assert not ed.editor.isHidden() and ed.preview.isHidden()
ed._set_mode("split")
assert not ed.editor.isHidden() and not ed.preview.isHidden()
ed.editor.setPlainText("# 新标题\n正文内容")
ed._render_preview()
assert "新标题" in ed.preview.toPlainText()
assert hasattr(dlg, "_open_fixed_editor")
print("✓ Markdown 编辑器就位（编辑/预览/分屏/meta）")

# 15. 面试自动作答（静默触发）
import config as _cfg_mod
assert _cfg_mod.DEFAULTS.get("interview_auto_answer") is True
assert hasattr(dlg, "iv_auto") and dlg.iv_auto.isChecked()
snap15 = dlg._snapshot()
assert "interview_auto_answer" in snap15
assert win._auto_answer_timer.interval() == 3000
assert win._auto_answer_timer.isSingleShot()
# pending 为空时不动作（阻断信号，避免 toggled 触发完整开关流程）
win._auto_answer_timer.stop()
win._qa_pending_text = []
win.interview_btn.blockSignals(True)
win.qa_btn.blockSignals(True)
win.interview_btn.setChecked(True)
win._auto_answer_tick()
assert not win._auto_answer_timer.isActive()
# 有 pending 时自动触发作答（无 API key，线程内报错安全），pending 被消费
win.qa_btn.setChecked(True)
win._qa_pending_text = ["请介绍一下你自己"]
win._auto_answer_tick()
assert win._qa_pending_text == []
# 开关关闭时 kick 不启动计时
win.cfg.data["interview_auto_answer"] = False
win._auto_answer_kick()
assert not win._auto_answer_timer.isActive()
win.cfg.data["interview_auto_answer"] = True
# 关闭面试/问答模式时计时器停止
win._auto_answer_timer.start()
win.interview_btn.setChecked(False)
win._toggle_interview(False)
assert not win._auto_answer_timer.isActive()
win._auto_answer_timer.start()
win._toggle_qa(False)
assert not win._auto_answer_timer.isActive()
print("✓ 面试自动作答就位（静默触发/开关/模式关闭停止计时）")

# 16. 上下文去重 + 资料库目录稳定性
win._ans_append("滚动测试内容")
assert "滚动测试内容" in win.answer.toPlainText()
win.answer.clear()
win._convo = ["面试官：介绍一下自己", "我：我是……", "面试官：项目中遇到什么难题"]
convo16 = win._convo_for_llm(["项目中遇到什么难题"])
assert "项目中遇到什么难题" not in convo16  # 本轮问题从对话记录剔除，避免重复
assert "介绍一下自己" in convo16 and "我：我是……" in convo16
# 多条 pending 逐条剔除；不在记录里的行不影响
win._convo = ["面试官：A", "面试官：B"]
assert win._convo_for_llm(["A", "B", "C"]) == ""
# 资料库目录：PROFILE_DIR 覆盖优先；非打包版回退到源码目录 profile/
import profile_store as ps16
_tmp_profile = os.environ["PROFILE_DIR"]
assert ps16.base_dir() == _tmp_profile
del os.environ["PROFILE_DIR"]
assert ps16.base_dir().endswith("profile") and "答题助手" in ps16.base_dir()
os.environ["PROFILE_DIR"] = _tmp_profile  # 恢复临时目录，防污染真实资料库
# 麦克风讲话在答案区只显示一行「正在说话」指示，不刷屏
win.answer.clear()
win._me_speaking_shown = False
win._on_transcript("me", "第一句话", None)
win._on_transcript("me", "第二句话", None)
assert win.answer.toPlainText().count("正在说话") == 1
win._on_transcript("interviewer", "面试官插话", None)
assert not win._me_speaking_shown  # 面试官插话后重置
win._on_transcript("me", "第三句话", None)
assert win.answer.toPlainText().count("正在说话") == 2  # 新一轮讲话再显示一次
win.answer.clear()
win._qa_pending_text = []
print("✓ 上下文去重/资料库稳定目录就位")

# 17. 隐身诊断/兼容模式 + 持续优化（场次保存/复盘注入）
import profile_store as ps17
assert hasattr(app_main, "get_display_affinity")
assert hasattr(dlg, "stealth_compat") and hasattr(dlg, "session_autosave")
assert hasattr(dlg, "iv_inject_review")
snap17 = dlg._snapshot()
for k in ("stealth_compat", "session_autosave", "inject_review"):
    assert k in snap17, k
assert win._stealth_compat is False  # 默认关闭，新系统用半透明样式
# 场次记录保存/读取
win._session_log = ["面试官：介绍项目", "我：我负责召回", "助手建议：可以这样说…"]
win.cfg.data["session_autosave"] = True
win.cfg.data["api_key"] = ""  # 无 key 时只保存记录，不触发复盘线程
win._save_session()
assert win._session_log == []  # 保存后清空，防止退出时重复保存
import glob as _glob
_sess = _glob.glob(os.path.join(os.environ["PROFILE_DIR"], "sessions", "*.md"))
assert len(_sess) == 1 and "面试官：介绍项目" in open(
    _sess[0], encoding="utf-8").read()
# 开关关闭时不保存
win.cfg.data["session_autosave"] = False
win._session_log = ["面试官：另一条"]
win._save_session()
assert len(_glob.glob(os.path.join(
    os.environ["PROFILE_DIR"], "sessions", "*.md"))) == 1
win.cfg.data["session_autosave"] = True
# 复盘注入上下文
ps17.save_fixed("固定文稿：推荐系统项目经历")
ps17.save_review("## 本场问题清单\n- 推荐系统召回")
c3 = llm.build_interview_content(
    {"api_key": "k", "model": "m", "inject_review": True}, "召回怎么做的")
assert "【面试复盘要点】" in c3 and "推荐系统召回" in c3
c4 = llm.build_interview_content(
    {"api_key": "k", "model": "m", "inject_review": False}, "召回怎么做的")
assert "【面试复盘要点】" not in c4
assert llm.REVIEW_PROMPT and hasattr(dlg, "_open_review_editor")
print("✓ 隐身诊断/兼容模式 + 持续优化（场次保存/复盘注入）就位")

# 18. 防噪机制 + 复盘归档 + 一键优化资料库
# 噪声门槛：杂音/语气词被过滤，真实短问题保留
assert app_main.is_noise_utterance("The.")
assert app_main.is_noise_utterance("嗯")
assert app_main.is_noise_utterance("呃，啊")
assert not app_main.is_noise_utterance("为什么")
assert not app_main.is_noise_utterance("然后呢")
assert not app_main.is_noise_utterance("介绍一下你自己")
# 截断识别：无标点/逗号/悬置词结尾 → 没说完
assert app_main.looks_incomplete("请问你为什么投递这个岗位")
assert app_main.looks_incomplete("你当时负责了项目的，")
assert app_main.looks_incomplete("我主要负责的是")
assert not app_main.looks_incomplete("你为这次面试做了哪些准备？")
assert not app_main.looks_incomplete("好的，我明白了。")
# 动态阈值：完整句 3 秒，截断痕迹 4 秒
win.interview_btn.blockSignals(True)
win.interview_btn.setChecked(True)
win.cfg.data["interview_auto_answer"] = True
win._qa_pending_text = ["你为这次面试做了哪些准备？"]
win._auto_answer_kick()
assert win._auto_answer_timer.interval() == 3000
win._auto_answer_timer.stop()
win._qa_pending_text = ["你为这次面试做了哪些"]
win._auto_answer_kick()
assert win._auto_answer_timer.interval() == 4000
win._auto_answer_timer.stop()
win.interview_btn.setChecked(False)
win.interview_btn.blockSignals(False)
# 回声判定：高度相似判回声，真实内容不误删
assert app_main.texts_similar(
    "我们来聊聊你参与的海南高企服务咨询平台项目",
    "我们来聊聊你参与的海南高企服务咨询平台。")
assert not app_main.texts_similar("嗯", "嗯")  # 太短不判定
assert not app_main.texts_similar(
    "我先说一下我的看法", "我们来聊聊高企平台项目")
# 复盘归档：reviews/ 时间戳 + interview_review.md 最新指针
_reviews_dir = os.path.join(os.environ["PROFILE_DIR"], "reviews")
_before = len(_glob.glob(os.path.join(_reviews_dir, "*.md")))
ps17.save_review("复盘一")
ps17.save_review("复盘二")
assert ps17.load_review() == "复盘二"
assert len(_glob.glob(os.path.join(_reviews_dir, "*.md"))) == _before + 2
# merge_flex：同标题覆盖、新主题追加、找不到的 update 转追加
_merged = ps17.merge_flex(
    [{"id": "1", "title": "推荐系统", "keywords": ["召回"], "content": "旧内容"}],
    [{"title": "推荐系统", "content": "新内容"},
     {"title": "不存在的", "content": "转追加"}],
    [{"title": "新主题", "keywords": ["x"], "content": "新增内容"}])
assert len(_merged) == 3
assert _merged[0]["content"] == "新内容" and _merged[0]["keywords"] == ["召回"]
# prompt_improvements 注入面试提示词（用户级）
c5 = llm.build_interview_content(
    {"api_key": "k", "model": "m", "prompt_improvements": "回答按 STAR 结构"},
    "召回怎么做的")
assert "【复盘改进要点】" in c5 and "STAR" in c5
assert hasattr(llm, "apply_review") and hasattr(dlg, "_apply_review")
# 上一个完整问题提取（听不清重试用）
win._convo = ["面试官：你为什么投递这个岗位？", "我：因为我……",
              "面试官：The"]
assert win._last_complete_question() == "你为什么投递这个岗位？"
print("✓ 防噪/复盘归档/一键优化资料库就位")

# ================= v2.0：mic 碎段合并 / 提示词迁移 / 独立思考开关 / 退出落盘 =================
# 碎段拼接：中文直接相连，英文补空格防粘词
assert app_main._join_utterances(["我是想说", "这个方案其实"]) == "我是想说这个方案其实"
assert app_main._join_utterances(["I used", "to walk"]) == "I used to walk"
assert app_main._join_utterances(["", None, "好"]) == "好"

# mic 合并缓冲：多段先入缓冲，flush 后合并为一条；面试官插话立即 flush 且时序正确
win.interview_btn.blockSignals(True); win.interview_btn.setChecked(True)
win.qa_btn.blockSignals(True); win.qa_btn.setChecked(True)
win._convo, win._session_log, win._recent_iv = [], [], []
win._me_buffer = []
win._on_transcript("me", "我是想说", None)
win._on_transcript("me", "这个方案其实", None)
assert win._session_log == [] and win._me_buffer == ["我是想说", "这个方案其实"]
win._flush_me_buffer()
assert win._session_log == ["我：我是想说这个方案其实"] and win._me_buffer == []
win._on_transcript("me", "还有一点补充", None)
win._on_transcript("interviewer", "好的，那我们聊聊下一个话题。", None)
assert win._session_log[-2] == "我：还有一点补充"
assert win._session_log[-1] == "面试官：好的，那我们聊聊下一个话题。"
win._auto_answer_timer.stop()  # 面试官文本触发的自动作答计时，测试中不触发
win._qa_pending_text = []
win.qa_btn.setChecked(False); win.qa_btn.blockSignals(False)
win.interview_btn.setChecked(False); win.interview_btn.blockSignals(False)

# 提示词迁移：v1.x 旧默认 -> 新默认（含朗读/语言条款），自定义不动
assert config.DEFAULTS["qa_thinking"] is False
_mig = config.AppConfig({"interview_prompt": config._INTERVIEW_PROMPT_V1})
assert _mig.data["interview_prompt"] == config.INTERVIEW_PROMPT
assert "朗读" in config.INTERVIEW_PROMPT and "什么语言" in config.INTERVIEW_PROMPT
_mig2 = config.AppConfig({"interview_prompt": "我自己的提示词"})
assert _mig2.data["interview_prompt"] == "我自己的提示词"

# thinking 透传：问答/面试走 qa_thinking（默认关），复盘等离线任务走主 thinking
_orig_chat = llm._openai_chat
_think_calls = []
def _think_spy(cfg, parts, thinking):
    _think_calls.append(thinking)
    return "OK"
llm._openai_chat = _think_spy
try:
    _tc = {"api_key": "k", "model": "m", "provider": "openai",
           "thinking": True, "qa_thinking": False}
    llm.ask_text(_tc, "问题")
    assert _think_calls[-1] is False      # 问答：qa_thinking 关
    llm.ask_interview(_tc, "问题", convo="")
    assert _think_calls[-1] is False      # 面试：qa_thinking 关
    llm.generate_review(_tc, "记录")
    assert _think_calls[-1] is True       # 复盘：主 thinking 开
    _tc["qa_thinking"] = True
    llm.ask_text(_tc, "问题")
    assert _think_calls[-1] is True       # 开关生效
finally:
    llm._openai_chat = _orig_chat

# 退出落盘链路：closeEvent 走模式关闭链（存场次+复位按钮），_save_session 幂等
import inspect as _insp
_ce_src = _insp.getsource(app_main.MainWindow.closeEvent)
assert "setChecked(False)" in _ce_src and "_stop_capture" in _ce_src
_qa_src = _insp.getsource(app_main.MainWindow._toggle_qa)
assert "_save_session" not in _qa_src  # 保存由联动的 _toggle_interview 完成
assert "_save_session" in _insp.getsource(app_main.MainWindow._toggle_interview)
assert "_flush_me_buffer" in _insp.getsource(app_main.MainWindow._save_session)
_sessions_dir = os.path.join(os.environ["PROFILE_DIR"], "sessions")
_sbefore = len(_glob.glob(os.path.join(_sessions_dir, "*.md")))
win._session_log = ["面试官：测试问题", "我：测试回答"]
_key_bak = win.cfg.data.get("api_key")
win.cfg.data["api_key"] = ""  # 无 key：保存文件但跳过复盘网络调用
win._save_session()
win._save_session()  # 第二次为空，不产生新文件
win.cfg.data["api_key"] = _key_bak
assert len(_glob.glob(os.path.join(_sessions_dir, "*.md"))) == _sbefore + 1, \
    (f"before={_sbefore} after={len(_glob.glob(os.path.join(_sessions_dir, '*.md')))} "
     f"autosave={win.cfg.data.get('session_autosave')} dir={_sessions_dir}")
# 设置界面：qa_thinking 开关存在且入快照
assert hasattr(dlg, "qa_thinking") and "qa_thinking" in dlg._snapshot()
print("✓ v2.0：mic 合并/提示词迁移/独立思考开关/退出落盘就位")

# ================= v2.1：秒退 + 启动补复盘 + 三组颜色透明度定制 =================
import inspect as _insp21
# 退出路径：_quit_app 只落盘不发起复盘网络请求，且 os._exit 秒退兜底
_quit_src = _insp21.getsource(app_main.MainWindow._quit_app)
assert "review=False" in _quit_src and "os._exit(0)" in _quit_src
# _save_session(review=False)：保存记录但不启动复盘线程
_sbefore21 = len(_glob.glob(os.path.join(_sessions_dir, "*.md")))
win._session_log = ["面试官：v2.1 测试", "我：测试回答"]
win.cfg.data["api_key"] = ""  # 双保险：即使误走复盘分支也无网络
win._review_thread = None
win._save_session(review=False)
assert win._review_thread is None  # 未启动复盘线程
assert len(_glob.glob(os.path.join(_sessions_dir, "*.md"))) == _sbefore21 + 1
win._save_session(review=False)
assert len(_glob.glob(os.path.join(_sessions_dir, "*.md"))) == _sbefore21 + 1  # 幂等

# 启动补复盘：session 比 review 新 -> 触发；review 更新后 -> 不触发
# 注意：main.py 是 from llm import generate_review，mock 必须打在 app_main 的本地绑定上
win.cfg.data["api_key"] = "k"
_win_review_calls = []
_orig_gen = app_main.generate_review
app_main.generate_review = lambda cfg, text: _win_review_calls.append(text) or "复盘"
try:
    win._review_thread = None
    win._maybe_backfill_review()
    assert win._review_thread is not None  # 已触发补生成线程
    win._review_thread.wait(3000)  # 等线程跑完（mock 立即返回）
    QApplication.processEvents()   # 泵 done 信号到 GUI 线程
    win._on_review_done("复盘", "")  # 兜底：确保复盘落盘（信号已到则只是多存一次）
    win._review_thread = None
    win._maybe_backfill_review()  # reviews/ 已更新 -> 幂等不再触发
    assert win._review_thread is None
    assert len(_win_review_calls) == 1
finally:
    app_main.generate_review = _orig_gen

# 颜色工具与样式参数化
assert app_main._hex_rgb("#181b22") == (24, 27, 34)
assert app_main._hex_rgb("bad") is None and app_main._hex_rgb("#12345") is None
assert app_main._rgba("#ff0000", 128) == "rgba(255, 0, 0, 128)"
_st = app_main._panel_style(100, "#102030", "#a0b0c0", 200)
assert "rgba(16, 32, 48, 100)" in _st and "rgba(160, 176, 192, 200)" in _st
_st_def = app_main._panel_style(205)
assert "rgba(24, 27, 34, 205)" in _st_def and "#e8eaf0" in _st_def.replace(
    "rgba(232, 234, 240, 255)", "#e8eaf0")  # 默认与旧版一致
# 答案区样式读取四键
win.cfg.data.update({"answer_bg_color": "#000000", "answer_bg_opacity": 0.5,
                     "answer_text_color": "#00ff00", "answer_text_opacity": 0.8})
win._apply_answer_style()
_ss = win.answer.styleSheet()
assert "rgba(0, 0, 0, 128)" in _ss and "rgba(0, 255, 0, 204)" in _ss
# 面板样式读取四键
win.cfg.data.update({"ui_bg_color": "#102030", "ui_bg_opacity": 1.0,
                     "ui_text_color": "#ffffff", "ui_text_opacity": 0.5})
win._apply_panel_style()
assert "rgba(16, 32, 48, 255)" in win.styleSheet()
win.cfg.data.update({  # 还原默认，避免影响后续/真实观感
    "answer_bg_color": "#ffffff", "answer_bg_opacity": 0.05,
    "answer_text_color": "#f2f4f8", "answer_text_opacity": 1.0,
    "ui_bg_color": "#181b22", "ui_bg_opacity": 0.80,
    "ui_text_color": "#e8eaf0", "ui_text_opacity": 1.0})
win._apply_answer_style(); win._apply_panel_style()
# 设置界面：四个色块按钮 + 两个字体透明度滑杆入快照
_snap21 = dlg._snapshot()
for _k in ("ui_bg_color", "ui_text_color", "ui_text_opacity",
           "answer_bg_color", "answer_text_color", "answer_text_opacity"):
    assert _k in _snap21, _k
print("✓ v2.1：秒退/启动补复盘/三组颜色透明度定制就位")

# ================= v2.1.1：保存防护 + 预设即时刷新 + 版本可见 + 异常日志 =================
assert app_main.APP_VERSION
# _save 异常路径：写配置失败 -> 红字提示 + 不关闭对话框 + 异常上抛（入 crash.log）
_dlg2 = app_main.SettingsDialog(win.cfg, win)
_orig_cfgsave = win.cfg.save
def _boom():
    raise OSError("磁盘被占用（模拟）")
win.cfg.save = _boom
try:
    _raised = False
    try:
        _dlg2._save()
    except OSError:
        _raised = True
    assert _raised and _dlg2.result() == 0  # 未 accept，界面保留
    assert "保存失败" in _dlg2.test_result.text()
finally:
    win.cfg.save = _orig_cfgsave
# 预设保存/删除即时刷新主窗口标题栏下拉（不再依赖设置页关闭）
from PySide6.QtWidgets import QInputDialog as _QID
_orig_gettext = _QID.getText
_QID.getText = staticmethod(lambda *a, **k: ("冒烟预设", True))
try:
    _before_items = [win.profile_bar.itemText(i)
                     for i in range(win.profile_bar.count())]
    _dlg2._save_profile()
    _after_items = [win.profile_bar.itemText(i)
                    for i in range(win.profile_bar.count())]
    assert "冒烟预设" not in _before_items and "冒烟预设" in _after_items
    assert "冒烟预设" in win.cfg.data["profiles"]
    _dlg2.profile_combo.setCurrentIndex(
        _dlg2.profile_combo.findText("冒烟预设"))
    _dlg2._delete_profile()
    _after_del = [win.profile_bar.itemText(i)
                  for i in range(win.profile_bar.count())]
    assert "冒烟预设" not in _after_del
    assert "冒烟预设" not in win.cfg.data["profiles"]
finally:
    _QID.getText = _orig_gettext
# 异常日志钩子可安装
app_main._install_crash_log()
import sys as _sys
assert _sys.excepthook is not _sys.__excepthook__
print("✓ v2.1.1：保存防护/预设即时刷新/版本可见/异常日志就位")

# ================= v2.2：秒关视觉优化 + 提示精简 + 主窗口外观实时面板 =================
assert app_main.APP_VERSION == "2.2"
# _quit_app：先隐藏窗口与托盘（视觉秒关），再做收尾
_qs = _insp21.getsource(app_main.MainWindow._quit_app)
assert _qs.index("self.hide()") < _qs.index("self._stop_capture()")
assert _qs.index("self.tray.hide()") < _qs.index("self._stop_capture()")
# 答题模型提示：精简为一句小字
_hints = [l.text() for l in dlg.findChildren(app_main.QLabel)
          if "图片输入" in l.text()]
assert any("多模态" in t and "deepseek-v4-flash-vision-exp" not in t
           for t in _hints), _hints
# 外观面板：默认隐藏，🎨 按钮可切换
assert hasattr(win, "look_btn") and win.look_btn.isCheckable()
assert hasattr(win, "look_panel") and not win.look_panel.isVisible()
for _k in ("window_opacity", "font_size", "ui_bg_color", "ui_bg_opacity",
           "ui_text_color", "ui_text_opacity", "answer_bg_color",
           "answer_bg_opacity", "answer_text_color", "answer_text_opacity"):
    assert _k in win._lk, _k
# 实时应用：字号 / 答案字体透明度 / UI 字体透明度 / 窗口不透明度
win._lk_apply("font_size", 18)
assert win.cfg.data["font_size"] == 18
assert "font-size: 18px" in win.answer.styleSheet()
win._lk_apply("answer_text_opacity", 0.5)
assert "rgba(242, 244, 248, 128)" in win.answer.styleSheet()
win._lk_apply("answer_text_opacity", 1.0)
win._lk_apply("ui_text_opacity", 0.5)
assert win.cfg.data["ui_text_opacity"] == 0.5
win._lk_apply("ui_text_opacity", 1.0)
win._lk_apply("window_opacity", 0.8)
assert win.cfg.data["window_opacity"] == 0.8
win._lk_apply("font_size", 14)
# 展开同步 + 收起保存
win.cfg.data["font_size"] = 20
_save_calls = []
win.cfg.save = lambda: _save_calls.append(1)
try:
    win.look_btn.setChecked(True)
    assert win.look_panel.isVisible()
    assert win._lk["font_size"].value() == 20  # 展开时同步最新配置
    win.look_btn.setChecked(False)
    assert not win.look_panel.isVisible()
    assert len(_save_calls) == 1  # 收起时统一落盘
finally:
    win.cfg.save = _orig_cfgsave
win.cfg.data["font_size"] = 14
# 沉浸式隐藏时收起外观面板（面板不在 _chrome 中）
assert "look_btn.setChecked(False)" in _insp21.getsource(
    app_main.MainWindow._set_immersive_ui)
print("✓ v2.2：秒关视觉优化/提示精简/外观实时调整面板就位")
print("✓ 全部冒烟测试通过")

QTimer.singleShot(100, app.quit)
app.exec()
