# -*- coding: utf-8 -*-
"""配置管理：读写 config.json（位于 exe 或脚本同目录）。"""
import json
import os
import sys

DEFAULT_PROMPT = (
    "你是一个网课答题助手。图片中是一道网课题目（可能包含题干和选项）。\n"
    "要求：\n"
    "1. 先识别题目内容；\n"
    "2. 第一行直接给出【答案】：选择题写选项字母+选项内容，判断题写 对/错，"
    "填空题/简答题写答案要点；\n"
    "3. 第二行起用一两句话给出简要理由；\n"
    "4. 不要输出与答题无关的内容。"
)

DEFAULTS = {
    "provider": "openai",                # openai | anthropic
    "base_url": "https://api.openai.com/v1",
    "api_key": "",
    "model": "",
    "prompt": DEFAULT_PROMPT,
    "region": None,                      # {"x":..,"y":..,"w":..,"h":..} 全局逻辑坐标
    "always_on_top": True,
    "window_opacity": 0.92,              # 0.5 ~ 1.0
    "monitor_interval_ms": 1500,         # 监控轮询间隔
    "thinking": True,                    # 默认开启思考模式
    "hotkey": "Ctrl+Alt+Q",              # 全局触发识别的快捷键
    "font_size": 14,                     # 答案区字号（px）
    "win_size": None,                    # 记住窗口大小 [w, h]
    "profiles": {},                      # 我的预设：{名称: {provider, base_url, api_key, model, thinking}}
}


def config_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


class AppConfig:
    def __init__(self, data: dict):
        self.data = dict(DEFAULTS)
        self.data.update(data or {})

    def __getattr__(self, name):
        try:
            return self.data[name]
        except KeyError:
            raise AttributeError(name)

    def set(self, key, value):
        self.data[key] = value

    @classmethod
    def load(cls) -> "AppConfig":
        try:
            with open(config_path(), "r", encoding="utf-8") as f:
                return cls(json.load(f))
        except Exception:
            return cls({})

    def save(self):
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
