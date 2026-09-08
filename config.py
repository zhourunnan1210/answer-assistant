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

# 问答助手专用提示词（与答题提示词独立）：口语化、结构化、可直接念出
QA_PROMPT = (
    "你是一位会议实时问答助手。下面是线上会议中语音识别出的讲话内容"
    "（可能有错别字，请结合上下文理解）。\n"
    "要求：\n"
    "1. 先判断对方提出的核心问题是什么；\n"
    "2. 给出适合直接口头念出来的回答：第一句话直接给结论，然后分点展开，"
    "每点一两句话；\n"
    "3. 语言口语化、自然，像人在现场回答，不要书面腔；\n"
    "4. 总长度控制在 150 字以内，便于快速念完；\n"
    "5. 如果内容里没有明确的问题，简要总结对方观点，并给出一句得体的回应。"
)

# 面试辅助专用提示词（与答题/问答提示词独立）：结合简历生成可口头念出的回答
INTERVIEW_PROMPT = (
    "你是一位面试实时辅助助手。下面会先给出求职者的简历内容，"
    "再给出线上面试中语音识别出的面试官讲话（可能有错别字，请结合上下文理解）。\n"
    "要求：\n"
    "1. 先判断面试官的核心问题是什么；\n"
    "2. 结合简历给出求职者可直接口头念出的回答：第一句话直接回应问题，"
    "然后分点展开，优先引用简历中的真实经历、项目和数据；\n"
    "3. 语言口语化、自信、自然，像本人现场回答，不要书面腔；\n"
    "4. 总长度控制在 200 字以内，便于快速念完；\n"
    "5. 问题涉及简历中没有的经历时，基于简历做合理延伸，"
    "不要编造与简历矛盾的内容；\n"
    "6. 如果内容里没有明确的问题，简要总结对方观点，并给出一句得体的回应。"
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
    # ---- 问答助手（语音识别 + 文本问答）----
    "qa_prompt": QA_PROMPT,              # 问答专用提示词
    "asr_source": "local",               # 语音识别来源：local（本地模型，推荐）| cloud（云端 API）
    "asr_use_same_key": False,           # 云端模式：语音识别是否复用答题服务商
    "asr_base_url": "https://api.siliconflow.cn/v1",
    "asr_api_key": "",
    "asr_model": "FunAudioLLM/SenseVoiceSmall",
    # ---- 面试辅助（简历上下文 + 面试提示词）----
    "interview_prompt": INTERVIEW_PROMPT,  # 面试专用提示词
    "resume_name": "",                     # 已加载简历的文件名（仅用于显示）
    "resume_text": "",                     # 简历解析后的纯文本
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
