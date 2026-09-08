# -*- coding: utf-8 -*-
"""答题助手 —— 半透明置顶悬浮窗，截取屏幕题目区域，调用多模态大模型给出答案。"""
import sys
import html
import json
import ctypes
from ctypes import wintypes
from datetime import datetime

from PySide6.QtCore import (Qt, QAbstractNativeEventFilter, QBuffer, QEvent,
                            QIODevice, QObject, QPoint, QRect, QThread,
                            QTimer, Signal)
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import (QColor, QGuiApplication, QIcon, QImage, QPainter,
                           QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QMenu,
                               QMessageBox, QInputDialog, QPlainTextEdit,
                               QPushButton, QSizeGrip, QSlider, QSpinBox,
                               QStackedWidget, QSystemTrayIcon, QTextEdit,
                               QVBoxLayout, QWidget)

from config import AppConfig, DEFAULT_PROMPT, QA_PROMPT
from audio_capture import LoopbackCapture, merge_wavs
from llm import (AUTO_PROMPT, ask_text, ask_vision, fetch_models,
                 test_asr, test_connection, transcribe_audio)

def combo_arrow_path() -> str:
    """运行时绘制下拉箭头小图标（深色背景下默认箭头几乎不可见），返回正斜杠路径。"""
    global _ARROW_PNG
    if _ARROW_PNG:
        return _ARROW_PNG
    import os
    import tempfile
    path = os.path.join(tempfile.gettempdir(), "dati_combo_arrow.png")
    if not os.path.exists(path):
        pix = QPixmap(20, 20)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#aab2c0"))
        p.drawPolygon([QPoint(6, 8), QPoint(14, 8), QPoint(10, 13)])
        p.end()
        pix.save(path)
    _ARROW_PNG = path.replace("\\", "/")
    return _ARROW_PNG


_ARROW_PNG = None

# 滚动条深色化（默认白底滚动条在深色面板上非常突兀）
SCROLLBAR_STYLE = """
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 2px; border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 50); min-height: 24px; border-radius: 5px;
}
QScrollBar::handle:vertical:hover { background: rgba(255, 255, 255, 80); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 2px; border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: rgba(255, 255, 255, 50); min-width: 24px; border-radius: 5px;
}
QScrollBar::handle:horizontal:hover { background: rgba(255, 255, 255, 80); }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }
"""

PANEL_STYLE_HEAD = """
QWidget#panel {
    background-color: rgba(24, 27, 34, 205);
    border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 12px;
}
QLabel { color: #e8eaf0; }
QLabel#title { font-size: 14px; font-weight: bold; color: #ffffff; }
QLabel#status { color: #a6adbb; font-size: 12px; }
QPushButton {
    background-color: rgba(255, 255, 255, 22);
    color: #e8eaf0; border: 1px solid rgba(255, 255, 255, 45);
    border-radius: 6px; padding: 5px 10px; font-size: 12px;
}
QPushButton:hover { background-color: rgba(255, 255, 255, 45); }
QPushButton:checked { background-color: rgba(70, 130, 240, 170); color: #ffffff; }
QPushButton:disabled { color: #777; }
QPushButton#primary {
    background-color: rgba(70, 130, 240, 190); color: white; font-weight: bold;
}
QPushButton#primary:hover { background-color: rgba(90, 150, 250, 220); }
/* 标题栏图标按钮：统一透明底 + 细描边，hover 微亮 */
QPushButton#icon {
    background: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 4px 8px; font-size: 13px; color: #cfd4de;
}
QPushButton#icon:hover { background: rgba(255, 255, 255, 28); }
/* 置顶按钮激活态：淡蓝描边而不是实心蓝块 */
QPushButton#icon:checked {
    background: rgba(90, 150, 250, 50);
    border: 1px solid rgba(120, 170, 255, 110);
    color: #bcd4ff;
}
/* 关闭按钮：hover 变红，提示"真退出" */
QPushButton#close:hover { background: rgba(224, 78, 78, 210); color: #ffffff; }
QTextEdit {
    background-color: rgba(255, 255, 255, 14);
    color: #f2f4f8; border: none; border-radius: 8px;
    font-size: 13px; padding: 6px;
}
QComboBox {
    background-color: rgba(255, 255, 255, 22);
    color: #e8eaf0; border: 1px solid rgba(255, 255, 255, 45);
    border-radius: 6px; padding: 3px 8px; font-size: 12px;
}
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView {
    background-color: #262a33; color: #e8eaf0;
    selection-background-color: #4a82f0;
    border: 1px solid rgba(255, 255, 255, 45);
}
QToolTip {
    background-color: #262a33; color: #e8eaf0;
    border: 1px solid rgba(255, 255, 255, 45); padding: 4px;
}
"""

PANEL_STYLE = PANEL_STYLE_HEAD  # 运行时拼接下拉箭头路径（见 _panel_style()）


def _with_arrow(style: str) -> str:
    return style + SCROLLBAR_STYLE + (
        "QComboBox::down-arrow { image: url(%s); width: 10px; height: 10px; }\n"
        % combo_arrow_path())


def _panel_style() -> str:
    return _with_arrow(PANEL_STYLE_HEAD)


# ------------------------------------------------------------------ 设置对话框
# 与主窗口一致的深色主题（对话框内容区不透明，避免白底割裂感）
DIALOG_STYLE = """
QDialog { background-color: #1e2129; }
QLabel { color: #e8eaf0; font-size: 12px; }
QLineEdit, QPlainTextEdit, QSpinBox {
    background-color: rgba(255, 255, 255, 16);
    color: #e8eaf0; border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 6px; padding: 4px 8px; font-size: 12px;
}
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {
    border: 1px solid #5a96fa;
}
QComboBox {
    background-color: rgba(255, 255, 255, 16);
    color: #e8eaf0; border: 1px solid rgba(255, 255, 255, 40);
    border-radius: 6px; padding: 4px 8px; font-size: 12px;
}
QComboBox:focus { border: 1px solid #5a96fa; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox QAbstractItemView {
    background-color: #262a33; color: #e8eaf0;
    selection-background-color: #4a82f0;
    border: 1px solid rgba(255, 255, 255, 45);
}
QSpinBox::up-button, QSpinBox::down-button {
    width: 16px; background: rgba(255, 255, 255, 12); border: none;
}
QCheckBox { color: #e8eaf0; font-size: 12px; }
QCheckBox::indicator {
    width: 15px; height: 15px;
    border: 1px solid rgba(255, 255, 255, 70); border-radius: 4px;
    background: rgba(255, 255, 255, 10);
}
QCheckBox::indicator:checked { background: #5a96fa; border-color: #5a96fa; }
QPushButton {
    background-color: rgba(255, 255, 255, 22);
    color: #e8eaf0; border: 1px solid rgba(255, 255, 255, 45);
    border-radius: 6px; padding: 5px 12px; font-size: 12px;
}
QPushButton:hover { background-color: rgba(255, 255, 255, 45); }
QPushButton:disabled { color: #777; }
QPushButton#primary {
    background-color: rgba(70, 130, 240, 190); color: white; font-weight: bold;
}
QPushButton#primary:hover { background-color: rgba(90, 150, 250, 220); }
QSlider::groove:horizontal {
    height: 4px; background: rgba(255, 255, 255, 30); border-radius: 2px;
}
QSlider::sub-page:horizontal { background: #5a96fa; border-radius: 2px; }
QSlider::handle:horizontal {
    width: 14px; margin: -6px 0; border-radius: 7px; background: #5a96fa;
}
QToolTip {
    background-color: #262a33; color: #e8eaf0;
    border: 1px solid rgba(255, 255, 255, 45); padding: 4px;
}
/* 设置对话框左侧导航栏 */
QListWidget {
    background: rgba(255, 255, 255, 10);
    border: 1px solid rgba(255, 255, 255, 30);
    border-radius: 8px; padding: 4px;
    font-size: 12px; color: #cfd4de; outline: none;
}
QListWidget::item { padding: 8px 10px; border-radius: 6px; }
QListWidget::item:selected { background: rgba(90, 150, 250, 80); color: #ffffff; }
QListWidget::item:hover:!selected { background: rgba(255, 255, 255, 20); }
"""


def _dialog_style() -> str:
    return _with_arrow(DIALOG_STYLE)


# ---------------------------------------------------------------- 工具函数

def grab_region(region: dict):
    """按全局逻辑坐标截取屏幕区域，返回 QPixmap（失败返回 None）。"""
    rect = QRect(region["x"], region["y"], region["w"], region["h"])
    screen = QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()
    geo = screen.geometry()
    local = rect.intersected(geo).translated(-geo.topLeft())
    if local.isEmpty():
        return None
    pix = screen.grabWindow(0, local.x(), local.y(), local.width(), local.height())
    return None if pix.isNull() else pix


def pixmap_to_png(pixmap) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.ReadWrite)
    pixmap.save(buf, "PNG")
    return bytes(buf.data())


def fingerprint(pixmap) -> bytes:
    """缩小为 64x64 灰度图字节，用于画面变化检测。"""
    img = pixmap.toImage().scaled(64, 64, Qt.IgnoreAspectRatio,
                                  Qt.SmoothTransformation)
    img = img.convertToFormat(QImage.Format_Grayscale8)
    ptr = img.bits()
    return bytes(ptr[: img.sizeInBytes()])


def diff_ratio(a: bytes, b: bytes, tol: int = 14) -> float:
    if not a or not b or len(a) != len(b):
        return 1.0
    changed = sum(1 for x, y in zip(a, b) if abs(x - y) > tol)
    return changed / len(a)


# ---- 自动作答辅助 ----

def _norm_box(box):
    """把模型返回的坐标框规范化为 0~1 的 [x1,y1,x2,y2]，非法返回 None。
    兼容 0~1 与 0~1000 两种坐标系。"""
    try:
        vals = [float(v) for v in box]
    except (TypeError, ValueError):
        return None
    if len(vals) != 4:
        return None
    if max(vals) > 2:  # 0~1000 归一化坐标（部分模型的习惯）
        vals = [v / 1000.0 for v in vals]
    vals = [min(max(v, 0.0), 1.0) for v in vals]
    if vals[2] <= vals[0] or vals[3] <= vals[1]:
        return None
    return vals


def parse_auto_answer(text: str):
    """从模型输出中解析 {answer, answer_box, next_box}，失败返回 None。"""
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        data = json.loads(text[i:j + 1])
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    box = _norm_box(data.get("answer_box"))
    if not box:
        return None
    next_box = _norm_box(data.get("next_box")) if data.get("next_box") else None
    return {"answer": str(data.get("answer") or "").strip(),
            "answer_box": box, "next_box": next_box}


def box_center(box, region: dict):
    """归一化坐标框中心 -> 全局逻辑像素坐标。"""
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    return (int(region["x"] + cx * region["w"]),
            int(region["y"] + cy * region["h"]))


def click_point(x: int, y: int):
    """在全局逻辑坐标 (x,y) 处模拟一次鼠标左键点击（换算屏幕缩放）。"""
    screen = QGuiApplication.screenAt(QPoint(x, y)) or QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio()
    u = ctypes.windll.user32
    u.SetCursorPos(int(x * dpr), int(y * dpr))
    u.mouse_event(0x0002, 0, 0, 0, 0)  # 左键按下
    u.mouse_event(0x0004, 0, 0, 0, 0)  # 左键抬起


# ---- 全局快捷键（免鼠标触发识别，避免浏览器检测到鼠标离开页面）----

MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
WM_HOTKEY = 0x0312

HOTKEYS = {
    "Ctrl+Alt+Q": (MOD_CONTROL | MOD_ALT, 0x51),   # VK Q
    "Ctrl+Alt+A": (MOD_CONTROL | MOD_ALT, 0x41),   # VK A
    "F9": (0, 0x77),                                # VK_F9
    "F10": (0, 0x78),                               # VK_F10
}

# 固定功能的快捷键（不与"识别快捷键"选项冲突）
HOTKEY_CYCLE = (MOD_CONTROL | MOD_ALT, 0x53, "Ctrl+Alt+S")  # 顺序切换预设
HOTKEY_CLEAR = (MOD_CONTROL | MOD_ALT, 0x43, "Ctrl+Alt+C")  # 清空答案区
HOTKEY_QA = (MOD_CONTROL | MOD_ALT, 0x57, "Ctrl+Alt+W")     # 问答模式：回答刚才的问题


class WinHotkeyFilter(QAbstractNativeEventFilter):
    """捕获 RegisterHotKey 注册的 WM_HOTKEY 线程消息，按热键 ID 分发。"""

    def __init__(self):
        super().__init__()
        self.handlers = {}  # {hotkey_id: callback}

    def nativeEventFilter(self, event_type, message):
        if event_type == "windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY:
                cb = self.handlers.get(msg.wParam)
                if cb:
                    cb()
        return False, 0


WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 2004(19041)+：窗口对采集/共享完全隐身
WDA_MONITOR = 0x1              # Windows 7+：共享/截图时窗口显示为黑色块


def set_capture_immune(win, on: bool = True) -> str:
    """让窗口对屏幕共享/录屏（getDisplayMedia、Graphics Capture 等）隐身。
    本机显示不受影响。
    返回 "exclude"（完全隐身）/ "monitor"（黑块回退）/ "off" / None（失败）。"""
    try:
        hwnd = int(win.winId())
        u = ctypes.windll.user32
        if not on:
            return "off" if u.SetWindowDisplayAffinity(hwnd, 0) else None
        if u.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            return "exclude"
        # 旧版系统（Win7 ~ Win10 1909）不支持完全隐身，回退为黑块模式：
        # 内容不会泄露，但共享方能看出有一个黑色窗口
        if u.SetWindowDisplayAffinity(hwnd, WDA_MONITOR):
            return "monitor"
        return None
    except Exception:
        return None


# ---------------------------------------------------------------- 区域框选

class RegionSelector(QWidget):
    selected = Signal(dict)
    cancelled = Signal()

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.setGeometry(QGuiApplication.primaryScreen().virtualGeometry())
        self._begin = None
        self._rect = QRect()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))
        if not self._rect.isNull():
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(self._rect, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            p.setPen(QPen(QColor(80, 160, 255), 2))
            p.drawRect(self._rect)
        p.setPen(QColor(255, 255, 255))
        p.drawText(24, 40, "拖动鼠标框选题目区域，松开确认；按 Esc 取消")

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._begin = e.position().toPoint()
            self._rect = QRect(self._begin, self._begin)
            self.update()

    def mouseMoveEvent(self, e):
        if self._begin is not None:
            self._rect = QRect(self._begin, e.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self._begin is not None:
            self._begin = None
            if self._rect.width() >= 20 and self._rect.height() >= 20:
                g = self.geometry()
                self.selected.emit({
                    "x": g.x() + self._rect.x(), "y": g.y() + self._rect.y(),
                    "w": self._rect.width(), "h": self._rect.height()})
                self.close()
            else:
                self._rect = QRect()
                self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancelled.emit()
            self.close()


# ---------------------------------------------------------------- 后台线程

class FuncThread(QThread):
    done = Signal(object, str)  # (结果, 错误信息)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(self._fn(), "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, str(exc))


class QaBridge(QObject):
    """把音频采集线程的回调安全地转入 GUI 线程（Signal 自动排队）。"""
    utterance = Signal(bytes)   # 一句完整语音的 wav 字节
    cap_error = Signal(str)     # 采集异常


# ---------------------------------------------------------------- 设置对话框

# 常用供应商预设：名称, provider, base_url
PRESETS = [
    ("Kimi 开放平台", "openai", "https://api.moonshot.cn/v1"),
    ("Kimi for Coding", "openai", "https://api.kimi.com/coding/v1"),
    ("DeepSeek（视觉模型：deepseek-v4-flash-vision-exp）", "openai",
     "https://api.deepseek.com/v1"),
    ("通义千问（阿里云百炼）", "openai",
     "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    ("OpenAI", "openai", "https://api.openai.com/v1"),
    ("Anthropic（Claude）", "anthropic", "https://api.anthropic.com"),
]


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(600)
        self.cfg = cfg

        # ================= 页 1：答题模型 =================
        page_model = QWidget()
        form = QFormLayout(page_model)
        form.setSpacing(10)
        form.setContentsMargins(4, 4, 4, 4)

        # 我的预设：保存/切换整套模型配置
        prof_row = QHBoxLayout()
        self.profile_combo = QComboBox()
        self._reload_profiles()
        self.profile_combo.activated.connect(self._load_profile)
        save_prof_btn = QPushButton("存为预设")
        save_prof_btn.setToolTip("把当前填写的配置保存为一个命名预设")
        save_prof_btn.clicked.connect(self._save_profile)
        del_prof_btn = QPushButton("删除")
        del_prof_btn.clicked.connect(self._delete_profile)
        prof_row.addWidget(self.profile_combo, stretch=1)
        prof_row.addWidget(save_prof_btn)
        prof_row.addWidget(del_prof_btn)
        form.addRow("我的预设", prof_row)

        self.preset = QComboBox()
        self.preset.addItem("自定义（手动填写下方各项）", None)
        for name, prov, url in PRESETS:
            self.preset.addItem(name, (prov, url))
        self.preset.activated.connect(self._apply_preset)
        form.addRow("供应商模板", self.preset)

        self.provider = QComboBox()
        self.provider.addItem("OpenAI 兼容（GPT / Kimi / 通义 / DeepSeek 等）", "openai")
        self.provider.addItem("Anthropic（Claude）", "anthropic")
        idx = self.provider.findData(cfg.provider)
        self.provider.setCurrentIndex(max(0, idx))
        form.addRow("接口格式", self.provider)

        self.base_url = QLineEdit(cfg.base_url)
        self.base_url.setPlaceholderText("如 https://api.openai.com/v1 或 https://api.anthropic.com")
        form.addRow("Base URL", self.base_url)

        self.api_key = QLineEdit(cfg.api_key)
        self.api_key.setEchoMode(QLineEdit.Password)
        form.addRow("API Key", self.api_key)

        model_row = QHBoxLayout()
        self.model = QComboBox(editable=True)
        self.model.setPlaceholderText("如 kimi-k2.6 / gpt-4o / claude-sonnet-4-5")
        if cfg.model:
            self.model.setCurrentText(cfg.model)
        self.fetch_btn = QPushButton("获取模型列表")
        self.fetch_btn.clicked.connect(self._fetch_models)
        model_row.addWidget(self.model, stretch=1)
        model_row.addWidget(self.fetch_btn)
        form.addRow("模型", model_row)

        self.thinking = QCheckBox("开启思考模式（Kimi K2 / Claude 等推理模型，更准但稍慢）")
        self.thinking.setChecked(bool(getattr(cfg, "thinking", True)))
        form.addRow("思考模式", self.thinking)

        hint = QLabel("提示：截图答题需要模型支持图片输入；DeepSeek 官方仅 "
                      "deepseek-v4-flash-vision-exp 支持图片。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#9aa3b2; font-size:11px;")
        form.addRow("", hint)

        self.prompt = QPlainTextEdit(cfg.prompt or DEFAULT_PROMPT)
        self.prompt.setFixedHeight(130)
        form.addRow("提示词", self.prompt)

        self.test_btn = QPushButton("测试连接", objectName="primary")
        self.test_btn.clicked.connect(self._test)
        test_row = QHBoxLayout()
        test_row.addWidget(self.test_btn)
        test_row.addStretch()
        form.addRow("", test_row)

        # ================= 页 2：问答助手 =================
        page_qa = QWidget()
        form_qa = QFormLayout(page_qa)
        form_qa.setSpacing(10)
        form_qa.setContentsMargins(4, 4, 4, 4)

        qa_note = QLabel("问答模式的「回答」始终由答题模型生成；"
                         "本页配置的是「语音识别」服务（把讲话转成文字）。")
        qa_note.setWordWrap(True)
        qa_note.setStyleSheet("color:#8fb8ff; font-size:11px;")
        form_qa.addRow("", qa_note)

        self.asr_same = QCheckBox("与答题模型同服务商（复用 Base URL 和 Key）")
        self.asr_same.setToolTip(
            "问答模式的「回答」始终使用答题模型，无需设置；\n"
            "本选项只决定「语音识别」服务是否也走同一家服务商。\n"
            "仅当答题服务商同时提供语音识别接口时勾选（如 SiliconFlow）；\n"
            "Kimi、DeepSeek 等没有语音识别接口，请不要勾选。")
        self.asr_same.setChecked(bool(cfg.data.get("asr_use_same_key", False)))
        form_qa.addRow("语音识别", self.asr_same)

        self.asr_base_url = QLineEdit(cfg.data.get("asr_base_url", ""))
        self.asr_base_url.setPlaceholderText("如 https://api.siliconflow.cn/v1")
        form_qa.addRow("ASR Base URL", self.asr_base_url)

        self.asr_api_key = QLineEdit(cfg.data.get("asr_api_key", ""))
        self.asr_api_key.setEchoMode(QLineEdit.Password)
        form_qa.addRow("ASR API Key", self.asr_api_key)

        asr_model_row = QHBoxLayout()
        self.asr_model = QLineEdit(cfg.data.get("asr_model", ""))
        self.asr_model.setPlaceholderText(
            "如 FunAudioLLM/SenseVoiceSmall 或 whisper-1")
        self.asr_test_btn = QPushButton("测试语音识别")
        self.asr_test_btn.setToolTip("向 ASR 服务发送一段 0.8 秒测试音，验证连通性")
        self.asr_test_btn.clicked.connect(self._test_asr)
        asr_model_row.addWidget(self.asr_model, stretch=1)
        asr_model_row.addWidget(self.asr_test_btn)
        form_qa.addRow("ASR 模型", asr_model_row)

        asr_hint = QLabel("语音识别推荐 SiliconFlow 的 SenseVoice（中文快且准，"
                          "有免费额度），或 OpenAI whisper-1 等 Whisper 兼容服务。")
        asr_hint.setWordWrap(True)
        asr_hint.setStyleSheet("color:#9aa3b2; font-size:11px;")
        form_qa.addRow("", asr_hint)

        self.qa_prompt = QPlainTextEdit(cfg.data.get("qa_prompt") or QA_PROMPT)
        self.qa_prompt.setFixedHeight(110)
        form_qa.addRow("问答提示词", self.qa_prompt)

        def _sync_asr_fields(checked):
            for w in (self.asr_base_url, self.asr_api_key):
                w.setEnabled(not checked)
        self.asr_same.toggled.connect(_sync_asr_fields)
        _sync_asr_fields(self.asr_same.isChecked())

        # ================= 页 3：通用 =================
        page_gen = QWidget()
        form_gen = QFormLayout(page_gen)
        form_gen.setSpacing(10)
        form_gen.setContentsMargins(4, 4, 4, 4)

        # 监控模式已下线：interval 控件仅保留以兼容配置快照，不加入任何页面
        self.interval = QSpinBox()
        self.interval.setRange(1, 10)
        self.interval.setSuffix(" 秒")
        self.interval.setValue(max(1, round(cfg.monitor_interval_ms / 1000)))

        self.hotkey = QComboBox()
        for k in HOTKEYS:
            self.hotkey.addItem(k)
        self.hotkey.setCurrentText(getattr(cfg, "hotkey", "Ctrl+Alt+Q"))
        form_gen.addRow("识别快捷键", self.hotkey)

        self.font_size = QSpinBox()
        self.font_size.setRange(10, 28)
        self.font_size.setSuffix(" px")
        self.font_size.setValue(int(getattr(cfg, "font_size", 14)))
        form_gen.addRow("答案字号", self.font_size)

        op_row = QHBoxLayout()
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(50, 100)
        self.opacity.setValue(round(cfg.window_opacity * 100))
        self.opacity_label = QLabel(f"{self.opacity.value()}%")
        self.opacity.valueChanged.connect(
            lambda v: self.opacity_label.setText(f"{v}%"))
        op_row.addWidget(self.opacity)
        op_row.addWidget(self.opacity_label)
        form_gen.addRow("窗口不透明度", op_row)

        # ================= 侧栏 + 卡片页 =================
        self.pages = QStackedWidget()
        self.pages.addWidget(page_model)
        self.pages.addWidget(page_qa)
        self.pages.addWidget(page_gen)

        self.nav = QListWidget()
        self.nav.addItems(["答题模型", "问答助手", "通用"])
        self.nav.setFixedWidth(118)
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        mid = QHBoxLayout()
        mid.setSpacing(10)
        mid.addWidget(self.nav)
        mid.addWidget(self.pages, stretch=1)

        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Save).setText("保存")
        btns.button(QDialogButtonBox.Cancel).setText("取消")
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        lay.addLayout(mid, stretch=1)
        lay.addWidget(self.test_result)
        lay.addWidget(btns)
        self.setStyleSheet(_dialog_style())

    def _test_asr(self):
        snap = self._snapshot()
        has_key = bool(snap.get("asr_api_key")) or (
            snap.get("asr_use_same_key") and snap.get("api_key"))
        if not has_key:
            self.test_result.setText("❌ 请先填写语音识别 API Key")
            return
        self.asr_test_btn.setEnabled(False)
        self.test_result.setText("正在测试语音识别（发送 0.8 秒测试音）…")
        self._asr_test_thread = FuncThread(lambda: test_asr(snap), self)
        self._asr_test_thread.done.connect(self._on_asr_test_done)
        self._asr_test_thread.start()

    def _on_asr_test_done(self, result, error):
        self.asr_test_btn.setEnabled(True)
        self.test_result.setText(
            "❌ 语音识别测试失败：" + error if error
            else f"✅ 语音识别服务连通：{result}")

    def _profiles(self) -> dict:
        return self.cfg.data.setdefault("profiles", {})

    def _reload_profiles(self, select: str = None):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("（选择预设即载入）", None)
        for name in self._profiles():
            self.profile_combo.addItem(name, name)
        if select:
            idx = self.profile_combo.findText(select)
            if idx >= 0:
                self.profile_combo.setCurrentIndex(idx)
        self.profile_combo.blockSignals(False)

    def _load_profile(self, _idx):
        name = self.profile_combo.currentData()
        p = self._profiles().get(name) if name else None
        if not p:
            return
        self.provider.setCurrentIndex(
            max(0, self.provider.findData(p.get("provider", "openai"))))
        self.base_url.setText(p.get("base_url", ""))
        self.api_key.setText(p.get("api_key", ""))
        self.model.setCurrentText(p.get("model", ""))
        self.thinking.setChecked(bool(p.get("thinking", True)))
        # 预设中的两种提示词一并载入（旧预设没有这些字段则保持现状）
        if p.get("prompt"):
            self.prompt.setPlainText(p["prompt"])
        if p.get("qa_prompt"):
            self.qa_prompt.setPlainText(p["qa_prompt"])
        self.test_result.setText(f"已载入预设「{name}」，点「保存」生效")

    def _save_profile(self):
        name, ok = QInputDialog.getText(self, "保存预设", "预设名称（如 DeepSeek、Kimi）：")
        name = (name or "").strip()
        if not ok or not name:
            return
        self._profiles()[name] = {
            "provider": self.provider.currentData(),
            "base_url": self.base_url.text().strip(),
            "api_key": self.api_key.text().strip(),
            "model": self.model.currentText().strip(),
            "thinking": self.thinking.isChecked(),
            "prompt": self.prompt.toPlainText().strip(),
            "qa_prompt": self.qa_prompt.toPlainText().strip(),
        }
        self.cfg.save()  # 预设立即写入配置文件
        self._reload_profiles(select=name)
        self.test_result.setText(f"✅ 预设「{name}」已保存")

    def _delete_profile(self):
        name = self.profile_combo.currentData()
        if name and name in self._profiles():
            del self._profiles()[name]
            self.cfg.save()
            self._reload_profiles()
            self.test_result.setText(f"已删除预设「{name}」")

    def _apply_preset(self, _index):
        data = self.preset.currentData()
        if not data:
            return
        prov, url = data
        self.provider.setCurrentIndex(max(0, self.provider.findData(prov)))
        self.base_url.setText(url)

    def _snapshot(self) -> dict:
        d = dict(self.cfg.data)
        d.update({
            "provider": self.provider.currentData(),
            "base_url": self.base_url.text().strip(),
            "api_key": self.api_key.text().strip(),
            "model": self.model.currentText().strip(),
            "thinking": self.thinking.isChecked(),
            "prompt": self.prompt.toPlainText().strip() or DEFAULT_PROMPT,
            "monitor_interval_ms": self.interval.value() * 1000,
            "hotkey": self.hotkey.currentText(),
            "font_size": self.font_size.value(),
            "window_opacity": self.opacity.value() / 100,
            "qa_prompt": self.qa_prompt.toPlainText().strip() or QA_PROMPT,
            "asr_use_same_key": self.asr_same.isChecked(),
            "asr_base_url": self.asr_base_url.text().strip(),
            "asr_api_key": self.asr_api_key.text().strip(),
            "asr_model": self.asr_model.text().strip(),
        })
        return d

    def _test(self):
        self.test_btn.setEnabled(False)
        self.test_result.setText("测试中…")
        snap = self._snapshot()
        self._thread = FuncThread(lambda: test_connection(snap), self)
        self._thread.done.connect(self._on_test_done)
        self._thread.start()

    def _on_test_done(self, result, error):
        self.test_btn.setEnabled(True)
        self.test_result.setText("❌ " + error if error else f"✅ 连接成功，模型回复：{result}")

    def _fetch_models(self):
        snap = self._snapshot()
        if not snap["api_key"]:
            self.test_result.setText("❌ 请先填写 API Key")
            return
        self.fetch_btn.setEnabled(False)
        self.test_result.setText("正在获取模型列表…")
        self._models_thread = FuncThread(lambda: fetch_models(snap), self)
        self._models_thread.done.connect(self._on_models_fetched)
        self._models_thread.start()

    def _on_models_fetched(self, models, error):
        self.fetch_btn.setEnabled(True)
        if error:
            self.test_result.setText("❌ 获取失败：" + error)
            return
        current = self.model.currentText().strip()
        self.model.clear()
        best = -1
        vision_count = 0
        for i, m in enumerate(models):
            self.model.addItem(m["id"])
            tips = []
            if m.get("image"):
                tips.append("✅支持图片输入")
                vision_count += 1
            elif m.get("image") is False:
                tips.append("不支持图片")
            if m.get("reasoning"):
                tips.append("支持思考模式")
            if m.get("context_length"):
                tips.append(f"上下文 {m['context_length']}")
            if tips:
                self.model.setItemData(i, "；".join(tips), Qt.ToolTipRole)
            if best < 0 and m.get("image") and m.get("reasoning"):
                best = i  # 优先推荐同时支持视觉+思考的模型
        if current:
            self.model.setCurrentText(current)
        elif best >= 0:
            self.model.setCurrentIndex(best)
        note = f"✅ 获取到 {len(models)} 个模型"
        if vision_count:
            note += f"，其中 {vision_count} 个支持图片输入（鼠标悬停可查看各模型能力）"
        self.test_result.setText(note)

    def _save(self):
        self.cfg.data.update(self._snapshot())
        self.cfg.save()
        self.accept()


# ---------------------------------------------------------------- 主窗口

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = AppConfig.load()
        self._drag_pos = None
        self._worker = None
        self._selector = None
        self._baseline = None
        self._change_hits = 0
        self._inflight = False
        self._auto_count = 0
        self._auto_pre_fp = None
        # 问答助手模式状态
        self._cap_thread = None       # 音频采集线程
        self._asr_thread = None       # 语音识别线程
        self._qa_thread = None        # 回答生成线程
        self._asr_busy = False        # ASR 请求进行中（期间新语音先攒着）
        self._pending_wavs = []       # ASR 忙时积压的语音段
        self._qa_pending_text = []    # 上次回答之后识别出的讲话文本

        # WindowDoesNotAcceptFocus + WA_ShowWithoutActivating：
        # 本窗口可正常点击/拖动，但永远不会从浏览器抢走键盘焦点，
        # 避免网课页面监听 blur/visibilitychange 误判"切出"。
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowTitle("答题助手")
        self.setMinimumSize(280, 320)
        size = self.cfg.data.get("win_size")
        if isinstance(size, list) and len(size) == 2:
            self.resize(max(280, size[0]), max(320, size[1]))  # 恢复上次的窗口大小
        else:
            self.resize(400, 480)
        self._apply_topmost()
        self.setWindowOpacity(self.cfg.window_opacity)

        panel = QWidget(objectName="panel")
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(8)

        # 标题栏
        bar = QHBoxLayout()
        bar.setSpacing(6)
        title = QLabel("🎯 答题助手", objectName="title")
        bar.addWidget(title)
        self.profile_bar = QComboBox()
        self.profile_bar.setMaximumWidth(150)
        self.profile_bar.setToolTip("快捷切换预设（选中后自动测试连接）")
        self.profile_bar.activated.connect(self._switch_profile)
        bar.addWidget(self.profile_bar)
        bar.addStretch()
        self.top_btn = QPushButton("📌", objectName="icon", toolTip="置顶 / 取消置顶")
        self.top_btn.setCheckable(True)
        self.top_btn.setChecked(self.cfg.always_on_top)
        self.top_btn.clicked.connect(self._toggle_topmost)
        set_btn = QPushButton("⚙", objectName="icon", toolTip="设置")
        set_btn.clicked.connect(self._open_settings)
        min_btn = QPushButton("—", objectName="icon", toolTip="最小化到系统托盘")
        min_btn.clicked.connect(self._minimize_to_tray)
        close_btn = QPushButton("✕", objectName="close", toolTip="退出程序")
        close_btn.clicked.connect(self._quit_app)
        for b in (self.top_btn, set_btn, min_btn, close_btn):
            bar.addWidget(b)
        lay.addLayout(bar)

        # 答案区
        self.answer = QTextEdit(readOnly=True,
                                placeholderText="点击「识别本题」，答案将显示在这里。")
        self._apply_font_size()
        lay.addWidget(self.answer, stretch=1)

        # 状态
        self.status = QLabel("就绪", objectName="status")
        lay.addWidget(self.status)

        # 问答助手：回答按钮（开启问答模式时才显示）
        self.qa_answer_btn = QPushButton("💬 回答刚才的问题（Ctrl+Alt+W）",
                                         objectName="primary")
        self.qa_answer_btn.setToolTip(
            "把最近识别到的讲话内容发给模型，生成口语化回答")
        self.qa_answer_btn.clicked.connect(self._qa_answer)
        self.qa_answer_btn.setVisible(False)
        lay.addWidget(self.qa_answer_btn)

        # 操作按钮
        ops = QHBoxLayout()
        ops.setSpacing(8)
        self.region_btn = QPushButton("▣ 框选区域", toolTip="框选题目所在屏幕区域")
        self.region_btn.clicked.connect(self._region_btn_clicked)
        self.ask_btn = QPushButton("🔍 识别本题", objectName="primary")
        self.ask_btn.clicked.connect(self.recognize_now)
        self.qa_btn = QPushButton("🎙 问答", toolTip="问答助手模式：监听会议声音，"
                                  "语音转文字后按 Ctrl+Alt+W 生成回答")
        self.qa_btn.setCheckable(True)
        self.qa_btn.toggled.connect(self._toggle_qa)
        # ---- 监控模式 / 自动模式暂时下线（按钮不显示，恢复时取消注释）----
        # self.monitor_btn = QPushButton("👁 监控: 关", toolTip="开启后画面变化自动识别")
        # self.monitor_btn.setCheckable(True)
        # self.monitor_btn.toggled.connect(self._toggle_monitor)
        # self.auto_btn = QPushButton("🤖 自动: 关",
        #                             toolTip="自动点击答案并翻页连续作答")
        # self.auto_btn.setCheckable(True)
        # self.auto_btn.toggled.connect(self._toggle_auto)
        self.monitor_btn = None  # 占位：内部引用均判空
        self.auto_btn = None
        ops.addWidget(self.region_btn)
        ops.addWidget(self.ask_btn, stretch=1)
        ops.addWidget(self.qa_btn)
        # ops.addWidget(self.monitor_btn)
        # ops.addWidget(self.auto_btn)
        # 右下角拖拽手柄：无边框窗口的大小调整
        grip = QSizeGrip(self)
        grip.setToolTip("拖拽调整窗口大小")
        ops.addWidget(grip, 0, Qt.AlignBottom | Qt.AlignRight)
        lay.addLayout(ops)

        self.setStyleSheet(_panel_style())

        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self._monitor_tick)

        self._update_region_btn()
        if not self.cfg.region:
            self.status.setText("尚未框选区域，请先点击「▣ 框选区域」")

        # 全局快捷键：全程无需移动鼠标到本窗口即可触发识别
        self._hotkey_filter = WinHotkeyFilter()
        QApplication.instance().installNativeEventFilter(self._hotkey_filter)
        self._register_hotkey()
        # 问答助手：采集线程 -> GUI 线程的桥接
        self._qa_bridge = QaBridge(self)
        self._qa_bridge.utterance.connect(self._on_utterance)
        self._qa_bridge.cap_error.connect(self._on_cap_error)
        self._refresh_hint()
        self._apply_capture_immunity()
        self._reload_profile_bar()
        self._setup_tray()

    # ---- 系统托盘 ----

    @staticmethod
    def _make_tray_icon() -> QIcon:
        pix = QPixmap(64, 64)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(QColor(74, 130, 240))
        p.setPen(Qt.NoPen)
        p.drawEllipse(4, 4, 56, 56)
        p.setPen(QColor("white"))
        f = p.font()
        f.setPixelSize(32)
        f.setBold(True)
        p.setFont(f)
        p.drawText(pix.rect(), Qt.AlignCenter, "答")
        p.end()
        return QIcon(pix)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self._make_tray_icon(), self)
        self.tray.setToolTip("答题助手")
        menu = QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self._bring_to_front)
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self._quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _minimize_to_tray(self):
        # 无边框+不接收焦点的窗口走任务栏最小化会缩成桌面角落的小残块，
        # 因此改为收进系统托盘
        self.hide()
        self.tray.showMessage("答题助手", "已最小化到系统托盘，点击托盘图标恢复",
                              QSystemTrayIcon.Information, 2000)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._bring_to_front()

    def _bring_to_front(self):
        """显示窗口并提到最前（全程不抢键盘焦点）。

        修复：窗口被 Win+D/显示桌面最小化后，普通 show() 不会还原，
        托盘"显示主窗口"看似没反应；NOACTIVATE 窗口也无法用
        activateWindow 提层级，这里直接 SetWindowPos。"""
        if self.isMinimized():
            self.showNormal()
        if not self.isVisible():
            self.show()
        u = ctypes.windll.user32
        flags = 0x0001 | 0x0002 | 0x0010  # SWP_NOSIZE|NOMOVE|NOACTIVATE
        hwnd = int(self.winId())
        u.SetWindowPos(hwnd, -1, 0, 0, 0, 0, flags)      # HWND_TOPMOST 提到最前
        if not self.cfg.always_on_top:
            u.SetWindowPos(hwnd, -2, 0, 0, 0, 0, flags)  # 再落回普通层级的顶部

    def changeEvent(self, e):
        # 被 Win+D / 显示桌面等系统方式最小化时改为收进托盘，
        # 避免无边框窗口缩成桌面角落的小残块、看似"消失"
        if e.type() == QEvent.WindowStateChange and self.isMinimized():
            QTimer.singleShot(0, self.hide)
        super().changeEvent(e)

    # ---- 窗口拖动 / 置顶 ----

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and e.position().y() < 44:
            self._drag_pos = e.globalPosition().toPoint() - self.pos()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, _):
        self._drag_pos = None

    def _apply_topmost(self):
        on = self.cfg.always_on_top
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.top_btn.setChecked(on) if hasattr(self, "top_btn") else None
        self.show()
        # setWindowFlag 可能重建窗口句柄，隐身属性需要重新设置
        self._apply_capture_immunity()

    def _apply_capture_immunity(self):
        # 默认始终隐身：屏幕共享/录屏时本窗口不可见（无开关）
        mode = set_capture_immune(self, True)
        if not hasattr(self, "status"):
            return
        if mode == "monitor":
            self.status.setText("共享隐身：系统版本较旧，共享时本窗口显示为黑块")
        elif mode is None:
            self.status.setText("隐身模式设置失败（需 Windows 10 2004 及以上）")

    def _toggle_topmost(self):
        self.cfg.set("always_on_top", self.top_btn.isChecked())
        self.cfg.save()
        self._apply_topmost()

    # ---- 全局快捷键 ----

    def _apply_font_size(self):
        n = int(self.cfg.data.get("font_size", 14))
        self.answer.setStyleSheet(f"font-size: {n}px;")

    # ---- 全局快捷键 ----

    HOTKEY_ID_ASK, HOTKEY_ID_CYCLE, HOTKEY_ID_CLEAR, HOTKEY_ID_QA = 1, 2, 3, 4
    ALL_HOTKEY_IDS = (HOTKEY_ID_ASK, HOTKEY_ID_CYCLE, HOTKEY_ID_CLEAR,
                      HOTKEY_ID_QA)

    def _register_hotkey(self):
        u = ctypes.windll.user32
        for hid in self.ALL_HOTKEY_IDS:
            u.UnregisterHotKey(None, hid)
        self._hotkey_filter.handlers = {
            self.HOTKEY_ID_ASK: self._on_hotkey,
            self.HOTKEY_ID_CYCLE: self._cycle_profile,
            self.HOTKEY_ID_CLEAR: self._clear_answer,
            self.HOTKEY_ID_QA: self._qa_answer,
        }
        name = self.cfg.data.get("hotkey", "Ctrl+Alt+Q")
        if name not in HOTKEYS:  # 兼容旧配置（如已删除的 Ctrl+Alt+S 选项）
            name = "Ctrl+Alt+Q"
        mod, vk = HOTKEYS[name]
        if not u.RegisterHotKey(None, self.HOTKEY_ID_ASK,
                                mod | MOD_NOREPEAT, vk):
            self.status.setText(
                f"快捷键 {name} 注册失败（可能被其他程序占用），请在设置中更换")
        for hid, spec in ((self.HOTKEY_ID_CYCLE, HOTKEY_CYCLE),
                          (self.HOTKEY_ID_CLEAR, HOTKEY_CLEAR),
                          (self.HOTKEY_ID_QA, HOTKEY_QA)):
            mod, vk, label = spec
            if not u.RegisterHotKey(None, hid, mod | MOD_NOREPEAT, vk):
                self.status.setText(f"快捷键 {label} 注册失败（可能被其他程序占用）")

    def _on_hotkey(self):
        # 与点击「识别本题」等效，但全程不需要移动鼠标
        self.recognize_now()

    def _clear_answer(self):
        """Ctrl+Alt+C：清空答案区，恢复默认 placeholder。"""
        self.answer.clear()
        self._refresh_hint()
        self.status.setText("答案区已清空")

    def _cycle_profile(self):
        """Ctrl+Alt+S：顺序切换到下一个预设。"""
        profiles = list(self.cfg.data.get("profiles", {}).keys())
        if not profiles:
            self.status.setText("没有可切换的预设，请先在设置中保存")
            return
        cur = self._current_profile_name()
        nxt = (profiles[(profiles.index(cur) + 1) % len(profiles)]
               if cur in profiles else profiles[0])
        idx = self.profile_bar.findText(nxt)
        if idx >= 0:
            self.profile_bar.setCurrentIndex(idx)
        self._apply_profile(nxt)

    def _refresh_hint(self):
        # 注意：QTextEdit 的 placeholder 只渲染第一行（Qt 限制），
        # 多行提示必须以灰色正文形式写入文档；后续 setMarkdown/setHtml
        # 会整体替换内容，无需额外清理。
        import html as _html
        hk = self.cfg.data.get("hotkey", "Ctrl+Alt+Q")
        if hk not in HOTKEYS:
            hk = "Ctrl+Alt+Q"
        name = self._current_profile_name()
        model = _html.escape(self.cfg.data.get("model") or "未配置模型")
        if name:
            head = f"当前预设：{_html.escape(name)}（{model}）"
        else:
            head = f"当前模型：{model}"
        # 信息层级：预设行亮色加粗，快捷键说明行暗灰次要
        self.answer.setHtml(
            f"<div style='color:#e6ebf5'><b>{head}</b></div>"
            f"<div style='color:#8a93a6'><br>"
            f"{_html.escape(hk)}：识别本题<br>"
            f"Ctrl+Alt+S：顺序切换预设<br>"
            f"Ctrl+Alt+C：清空答案<br>"
            f"Ctrl+Alt+W：回答刚才的问题（需开启问答模式）"
            f"</div>")
        self.answer.setPlaceholderText("点击「识别本题」或按快捷键")

    # ---- 问答助手模式 ----

    def _toggle_qa(self, on: bool):
        if on:
            snap = self.cfg.data
            has_key = bool(snap.get("asr_api_key")) or (
                snap.get("asr_use_same_key") and snap.get("api_key"))
            if not has_key:
                self.status.setText("请先在 ⚙设置 的「问答助手」分组中配置语音识别服务")
                self.qa_btn.setChecked(False)
                return
            self._qa_pending_text = []
            self._pending_wavs = []
            self.answer.clear()
            self.answer.append(
                "<span style='color:#8a93a6'>🎙 问答模式已开启，正在监听会议声音…<br>"
                "识别到讲话会滚动显示在这里；听到问题后点下方按钮或按 "
                "Ctrl+Alt+W 生成回答。</span>")
            self.qa_btn.setText("🎙 问答中")
            self.qa_answer_btn.setVisible(True)
            self._cap_thread = LoopbackCapture(
                self._qa_bridge.utterance.emit, self._qa_bridge.cap_error.emit)
            self._cap_thread.start()
            self.status.setText("问答模式：监听系统声音中…")
        else:
            self._stop_capture()
            self.qa_btn.setText("🎙 问答")
            self.qa_answer_btn.setVisible(False)
            self.status.setText("问答模式已关闭")

    def _stop_capture(self):
        t = self._cap_thread
        self._cap_thread = None
        if t is not None:
            t.stop()

    def _on_cap_error(self, msg):
        self.status.setText(f"音频采集失败：{msg[:60]}")
        if self.qa_btn.isChecked():
            self.qa_btn.setChecked(False)

    def _on_utterance(self, wav: bytes):
        """采集线程切出一句完整语音（经 QaBridge 转入 GUI 线程）。"""
        if not self.qa_btn.isChecked():
            return
        if self._asr_busy:
            self._pending_wavs.append(wav)  # ASR 忙时先攒着，空闲后合并识别
            return
        self._start_asr(wav)

    def _start_asr(self, wav: bytes):
        self._asr_busy = True
        snap = dict(self.cfg.data)
        self._asr_thread = FuncThread(lambda: transcribe_audio(snap, wav), self)
        self._asr_thread.done.connect(self._on_transcript)
        self._asr_thread.start()

    def _on_transcript(self, text, err):
        self._asr_busy = False
        if err:
            self.status.setText(f"语音识别失败：{err[:60]}")
        elif text:
            self._qa_pending_text.append(text)
            self.answer.append(
                f"<span style='color:#8a93a6'>听到：{html.escape(text)}</span>")
        if self._pending_wavs:
            merged = merge_wavs(self._pending_wavs)
            self._pending_wavs.clear()
            self._start_asr(merged)

    def _qa_answer(self):
        """Ctrl+Alt+W 或按钮：把识别到的讲话内容发给 LLM 生成口语化回答。"""
        if not self.qa_btn.isChecked():
            self.status.setText("请先开启「🎙 问答」模式")
            return
        if self._qa_thread is not None and self._qa_thread.isRunning():
            self.status.setText("正在生成回答，请稍候…")
            return
        if not self._qa_pending_text:
            self.status.setText("还没有识别到讲话内容")
            return
        question = "\n".join(self._qa_pending_text)
        self._qa_pending_text = []
        self.answer.append(f"<b>❓ {html.escape(question[:120])}</b>")
        self.status.setText("正在生成回答…")
        snap = dict(self.cfg.data)
        self._qa_thread = FuncThread(lambda: ask_text(snap, question), self)
        self._qa_thread.done.connect(self._on_qa_answered)
        self._qa_thread.start()

    def _on_qa_answered(self, text, err):
        if err:
            self.status.setText("回答生成失败")
            self.answer.append(
                f"<span style='color:#e07878'>回答失败：{html.escape(err)}</span>")
        else:
            self.status.setText("回答已生成 ✅")
            body = html.escape(text).replace("\n", "<br>")
            self.answer.append(
                f"<span style='color:#f2f4f8'>💬 {body}</span><br>")

    # ---- 预设快捷切换 ----

    PROFILE_KEYS = ("provider", "base_url", "api_key", "model", "thinking",
                    "prompt", "qa_prompt")

    def _current_profile_name(self):
        """当前配置与某个预设一致时返回预设名，否则返回 None。
        预设中缺失的字段（如旧版预设没有 prompt）视为匹配，向后兼容。"""
        for name, p in self.cfg.data.get("profiles", {}).items():
            if all(self.cfg.data.get(k) == p.get(k, self.cfg.data.get(k))
                   for k in self.PROFILE_KEYS):
                return name
        return None

    def _reload_profile_bar(self, select: str = None):
        self.profile_bar.blockSignals(True)
        self.profile_bar.clear()
        profiles = self.cfg.data.get("profiles", {})
        if not profiles:
            self.profile_bar.addItem("无预设", None)
        else:
            for name in profiles:
                self.profile_bar.addItem(name, name)
            cur = select or self._current_profile_name()
            if cur:
                idx = self.profile_bar.findText(cur)
                if idx >= 0:
                    self.profile_bar.setCurrentIndex(idx)
        self.profile_bar.blockSignals(False)

    def _switch_profile(self, _idx):
        name = self.profile_bar.currentData()
        if name:
            self._apply_profile(name)

    def _apply_profile(self, name):
        p = self.cfg.data.get("profiles", {}).get(name)
        if not p:
            return
        self.cfg.data.update(p)
        self.cfg.save()
        self._refresh_hint()
        self.status.setText(f"正在测试预设「{name}」…")
        snap = dict(self.cfg.data)
        self._test_thread = FuncThread(lambda: test_connection(snap), self)
        self._test_thread.done.connect(
            lambda r, e, n=name: self._on_profile_tested(n, r, e))
        self._test_thread.start()

    def _on_profile_tested(self, name, result, error):
        if error:
            self.status.setText(f"预设「{name}」连接测试失败")
            self.answer.setMarkdown(
                f"**预设「{name}」连接测试失败**\n\n```\n{error}\n```")
        else:
            self.status.setText(f"预设「{name}」已切换，连接测试通过 ✅")
            self._refresh_hint()

    def _quit_app(self):
        self._stop_capture()
        self.cfg.set("win_size", [self.width(), self.height()])
        self.cfg.save()
        for hid in self.ALL_HOTKEY_IDS:
            ctypes.windll.user32.UnregisterHotKey(None, hid)
        self.tray.hide()
        QApplication.instance().quit()

    def closeEvent(self, e):
        self._stop_capture()
        for hid in self.ALL_HOTKEY_IDS:
            ctypes.windll.user32.UnregisterHotKey(None, hid)
        self.cfg.set("win_size", [self.width(), self.height()])
        self.cfg.save()
        super().closeEvent(e)

    # ---- 设置 ----

    def _open_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        set_capture_immune(dlg, True)  # 设置对话框（含API Key）同样隐身
        if dlg.exec() == QDialog.Accepted:
            self.setWindowOpacity(self.cfg.window_opacity)
            self._register_hotkey()
            self._refresh_hint()
            self._apply_font_size()
            self._apply_capture_immunity()
            self._reload_profile_bar()  # 预设可能被增删，刷新标题栏下拉
            if (self.monitor_btn is not None and self.monitor_btn.isChecked()):
                self.monitor_timer.start(self.cfg.monitor_interval_ms)

    # ---- 区域框选 ----

    def _update_region_btn(self):
        if self.cfg.region:
            self.region_btn.setText("✕ 取消框选")
            self.region_btn.setToolTip("清除已保存的题目区域，之后可重新框选")
        else:
            self.region_btn.setText("▣ 框选区域")
            self.region_btn.setToolTip("框选题目所在屏幕区域")

    def _region_btn_clicked(self):
        if self.cfg.region:
            self.cfg.set("region", None)
            self.cfg.save()
            self._baseline = None
            if self.monitor_btn is not None and self.monitor_btn.isChecked():
                self.monitor_btn.setChecked(False)  # 联动关闭监控
            if self.auto_btn is not None and self.auto_btn.isChecked():
                self.auto_btn.setChecked(False)     # 联动关闭自动模式
            self.status.setText("已取消框选，点击「框选区域」可重新框选")
            self._update_region_btn()
        else:
            self._select_region()

    def _select_region(self):
        self._selector = RegionSelector()
        self._selector.selected.connect(self._on_region_selected)
        self._selector.show()
        set_capture_immune(self._selector, True)  # 框选遮罩同样隐身

    def _on_region_selected(self, region: dict):
        self.cfg.set("region", region)
        self.cfg.save()
        self._baseline = None
        self._update_region_btn()
        self.status.setText(
            f"区域已保存：{region['w']}×{region['h']} @ ({region['x']},{region['y']})")

    # ---- 识别 ----

    def recognize_now(self):
        if self._inflight:
            self.status.setText("正在识别中，请稍候…")
            return
        if not self.cfg.region:
            self.status.setText("请先框选题目区域")
            self._select_region()
            return
        self._inflight = True
        self._capture_hidden_and_ask(manual=True)

    def _capture_hidden_and_ask(self, manual: bool, auto: bool = False):
        self.hide()  # 短暂隐藏自身，避免半透明窗口入镜
        QTimer.singleShot(260, lambda: self._grab_and_send(manual, auto))

    def _grab_and_send(self, manual: bool, auto: bool = False):
        pix = grab_region(self.cfg.region) if self.cfg.region else None
        self.show()
        if pix is None:
            self._inflight = False
            self.status.setText("截图失败，请重新框选区域")
            if (auto and self.auto_btn is not None
                    and self.auto_btn.isChecked()):
                self.auto_btn.setChecked(False)
            return
        png = pixmap_to_png(pix)
        snap = dict(self.cfg.data)
        if auto:
            snap["prompt"] = AUTO_PROMPT  # 自动模式要求模型返回选项坐标
        self.ask_btn.setEnabled(False)
        self.status.setText("识别中…")
        # 切换题目：先清空答案区，避免旧答案残留误导
        self.answer.setHtml("<span style='color:#9aa3b2'>识别中…</span>")
        self._worker = FuncThread(lambda: ask_vision(snap, png), self)
        self._worker.done.connect(lambda r, e: self._on_answer(r, e, manual, auto))
        self._worker.start()

    def _on_answer(self, result, error, manual: bool, auto: bool = False):
        self.ask_btn.setEnabled(True)
        ts = datetime.now().strftime("%H:%M:%S")
        auto_data = None
        if (auto and not error and self.auto_btn is not None
                and self.auto_btn.isChecked()):
            auto_data = parse_auto_answer(result)
        if error:
            self.status.setText("识别失败")
            self.answer.setMarkdown(f"**[{ts}] 识别失败**\n\n```\n{error}\n```")
        else:
            self.status.setText("识别完成 ✅")
            show = result
            if auto_data and auto_data["answer"]:
                show = auto_data["answer"] + "\n\n（已自动点击选项）"
            self.answer.setMarkdown(f"**[{ts}] 答案**\n\n{show}")
        self._inflight = False
        if self.monitor_btn is not None and self.monitor_btn.isChecked():
            # 答案刷新后窗口像素变化，延迟重建基线避免误触发
            self._baseline = None
            QTimer.singleShot(900, self._reset_baseline)
        if (auto and self.auto_btn is not None
                and self.auto_btn.isChecked()):
            if error:
                self.status.setText("识别出错，自动模式已停止")
                self.auto_btn.setChecked(False)
            elif not auto_data:
                self.status.setText("无法定位选项位置，自动模式已停止（答案已显示）")
                self.auto_btn.setChecked(False)
            else:
                self.status.setText("自动点击答案选项…")
                self.hide()  # 点击前隐藏自身，防止点到本窗口
                QTimer.singleShot(300, lambda: self._auto_click(auto_data))

    # ---- 自动作答模式 ----

    def _toggle_auto(self, on: bool):
        self.auto_btn.setText("🤖 自动: 开" if on else "🤖 自动: 关")
        if on:
            if not self.cfg.region:
                self.status.setText("请先框选题目区域")
                self.auto_btn.setChecked(False)
                self._select_region()
                return
            ret = QMessageBox.question(
                self, "确认开启自动模式",
                "自动模式将【自动点击】框选区域内的答案选项并翻页，连续作答。\n"
                "请确认：框选区域就是题目区域、选项可直接点击，"
                "且你已了解相关平台规则。\n\n确定开启？")
            if ret != QMessageBox.Yes:
                self.auto_btn.setChecked(False)
                return
            if self.monitor_btn.isChecked():
                self.monitor_btn.setChecked(False)  # 自动模式自带换题检测
            self._auto_count = 0
            self._auto_pre_fp = None
            self.status.setText("自动模式：识别当前题…")
            self._inflight = True
            self._capture_hidden_and_ask(manual=False, auto=True)
        else:
            self.status.setText("自动模式已停止")

    def _auto_click(self, data: dict):
        if not self.auto_btn.isChecked() or not self.cfg.region:
            self.show()
            return
        try:
            x, y = box_center(data["answer_box"], self.cfg.region)
            click_point(x, y)
        except Exception as exc:  # noqa: BLE001
            self.show()
            self.status.setText(f"自动点击失败：{exc}")
            self.auto_btn.setChecked(False)
            return
        if data.get("next_box"):
            QTimer.singleShot(800, lambda: self._auto_click_next(data["next_box"]))
        else:
            QTimer.singleShot(500, self._auto_after_clicks)

    def _auto_click_next(self, next_box):
        try:
            x, y = box_center(next_box, self.cfg.region)
            click_point(x, y)
        except Exception:  # noqa: BLE001
            pass
        QTimer.singleShot(600, self._auto_after_clicks)

    def _auto_after_clicks(self):
        self.show()
        self.status.setText("自动模式：等待切换到下一题…")
        QTimer.singleShot(200, self._auto_snapshot_baseline)

    def _auto_snapshot_baseline(self):
        """界面恢复后采集基线画面，用于检测是否切到下一题。"""
        pix = grab_region(self.cfg.region) if self.cfg.region else None
        self._auto_pre_fp = fingerprint(pix) if pix is not None else None
        QTimer.singleShot(800, lambda: self._auto_wait_change(0))

    def _auto_wait_change(self, attempts: int):
        if not self.auto_btn.isChecked() or not self.cfg.region:
            return
        pix = grab_region(self.cfg.region)
        if pix is not None and self._auto_pre_fp is not None:
            if diff_ratio(fingerprint(pix), self._auto_pre_fp) > 0.03:
                self._auto_count += 1
                if self._auto_count >= 200:  # 安全上限
                    self.status.setText("已达连答上限（200 题），自动模式停止")
                    self.auto_btn.setChecked(False)
                    return
                self.status.setText(f"自动模式：识别第 {self._auto_count + 1} 题…")
                self._inflight = True
                self._capture_hidden_and_ask(manual=False, auto=True)
                return
        if attempts >= 10:  # 约 10 秒无变化则停止
            self.status.setText("页面未切换到新题目，自动模式已停止")
            self.auto_btn.setChecked(False)
            return
        QTimer.singleShot(1000, lambda: self._auto_wait_change(attempts + 1))

    # ---- 监控模式 ----

    def _toggle_monitor(self, on: bool):
        if on and self.auto_btn.isChecked():
            self.status.setText("自动模式运行中，自带换题检测，无需开启监控")
            self.monitor_btn.setChecked(False)
            return
        self.monitor_btn.setText("👁 监控: 开" if on else "👁 监控: 关")
        if on:
            if not self.cfg.region:
                self.status.setText("请先框选题目区域")
                self.monitor_btn.setChecked(False)
                self._select_region()
                return
            self._baseline = None
            self._change_hits = 0
            self.monitor_timer.start(self.cfg.monitor_interval_ms)
            self.status.setText("监控中：画面变化将自动识别")
        else:
            self.monitor_timer.stop()
            self.status.setText("监控已关闭")

    def _reset_baseline(self):
        if self.cfg.region and not self._inflight:
            pix = grab_region(self.cfg.region)
            if pix is not None:
                self._baseline = fingerprint(pix)

    def _monitor_tick(self):
        if self._inflight or not self.cfg.region:
            return
        pix = grab_region(self.cfg.region)
        if pix is None:
            return
        fp = fingerprint(pix)
        if self._baseline is None:
            self._baseline = fp
            return
        if diff_ratio(fp, self._baseline) > 0.03:
            self._change_hits += 1
            if self._change_hits >= 2:  # 连续两轮变化才触发，过滤抖动
                self._change_hits = 0
                self._inflight = True
                self.status.setText("检测到新题目，识别中…")
                self._capture_hidden_and_ask(manual=False)
        else:
            self._change_hits = 0


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 窗口收进托盘后程序继续运行

    # 单实例：已有实例在运行时，通知它把窗口提到最前，然后直接退出。
    # 避免托盘里已有一个实例时再双击 exe 开出一个看不见的新窗口。
    key = "dati-zhushou-single-instance"
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(300):
        sock.write(b"raise")
        sock.flush()
        sock.waitForBytesWritten(300)
        return

    win = MainWindow()

    server = QLocalServer(app)
    QLocalServer.removeServer(key)  # 清理上次异常退出残留的监听
    server.listen(key)

    def _on_second_instance():
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.readyRead.connect(
                lambda c=conn: (c.readAll(), win._bring_to_front(),
                                c.disconnectFromServer()))

    server.newConnection.connect(_on_second_instance)

    win.show()
    win._bring_to_front()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
