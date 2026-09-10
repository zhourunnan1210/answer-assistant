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

# 面试辅助专用提示词（与答题/问答提示词独立）：结合固定文稿、专题资料与对话记录
INTERVIEW_PROMPT = (
    "你是一位面试实时辅助助手。下面会依次给出：候选人的固定文稿（个人介绍与项目经历）、"
    "专题资料索引、与当前问题相关的专题资料、到目前为止的面试对话记录，"
    "以及面试官最新的讲话（语音识别可能有错别字，请结合上下文理解）。\n"
    "要求：\n"
    "1. 结合对话记录判断当前正在聊哪个项目/哪段经历，抓住面试官的核心问题；\n"
    "2. 给出候选人可直接口头念出的回答：第一句话直接回应问题，然后分点展开，"
    "优先引用固定文稿和专题资料中的真实经历、技术细节和数据；\n"
    "3. 与对话记录中候选人已经说过的内容保持连贯、不自相矛盾，"
    "可以自然承接（如「对，除了刚才说的……」）；\n"
    "4. 语言口语化、自信、自然，像本人现场回答，不要书面腔；\n"
    "5. 总长度控制在 200 字以内，便于快速念完；\n"
    "6. 资料中没有的经历不要编造，不要与文稿内容矛盾；\n"
    "7. 如果没有明确的问题，简要总结对方观点，并给出一句得体的回应；\n"
    "8. 若【面试官最新讲话】只是无意义碎片（单个词、拟声词、明显识别错误），"
    "不要说「听不清」，请结合对话记录回答面试官上一个完整问题；\n"
    "9. 若面试官要求朗读材料、跟读、或在屏幕上操作演示（这类环节需要候选人"
    "直接执行动作，你看不到屏幕内容），不要编造内容，直接给出一句简短指引，"
    "如「请按屏幕上显示的材料朗读」；\n"
    "10. 面试官用什么语言提问，就用什么语言回答。"
)

# v1.x 旧版面试提示词（用于老用户配置迁移：配置里存的若仍是旧默认，升级为新版）
_INTERVIEW_PROMPT_V1 = (
    "你是一位面试实时辅助助手。下面会依次给出：候选人的固定文稿（个人介绍与项目经历）、"
    "专题资料索引、与当前问题相关的专题资料、到目前为止的面试对话记录，"
    "以及面试官最新的讲话（语音识别可能有错别字，请结合上下文理解）。\n"
    "要求：\n"
    "1. 结合对话记录判断当前正在聊哪个项目/哪段经历，抓住面试官的核心问题；\n"
    "2. 给出候选人可直接口头念出的回答：第一句话直接回应问题，然后分点展开，"
    "优先引用固定文稿和专题资料中的真实经历、技术细节和数据；\n"
    "3. 与对话记录中候选人已经说过的内容保持连贯、不自相矛盾，"
    "可以自然承接（如「对，除了刚才说的……」）；\n"
    "4. 语言口语化、自信、自然，像本人现场回答，不要书面腔；\n"
    "5. 总长度控制在 200 字以内，便于快速念完；\n"
    "6. 资料中没有的经历不要编造，不要与文稿内容矛盾；\n"
    "7. 如果没有明确的问题，简要总结对方观点，并给出一句得体的回应；\n"
    "8. 若【面试官最新讲话】只是无意义碎片（单个词、拟声词、明显识别错误），"
    "不要说「听不清」，请结合对话记录回答面试官上一个完整问题。"
)

# 信息初始化：原始资料 -> 固定文稿（LLM 整理归纳，用户可再手动修改）
PROFILE_BUILD_PROMPT = (
    "你是一位求职资料整理助手。下面是求职者的原始资料（简历、个人信息等）。\n"
    "请整理归纳成一份「固定文稿」，供面试问答时作为候选人背景使用。\n"
    "要求：\n"
    "1. 用简体中文 Markdown，结构为：# 个人介绍（150 字以内、口语化、可直接念出的"
    "自我介绍说辞）；# 过往项目/经历（每段含：项目名称、角色、时间、技术栈、"
    "核心贡献与可量化成果，各 200 字以内）；# 技能清单（一行式罗列）；\n"
    "2. 只保留与求职/面试相关的信息，删除电话、邮箱等隐私细节；\n"
    "3. 不要编造资料中没有的内容；\n"
    "4. 总长度控制在 2500 字以内；\n"
    "5. 直接输出文稿内容，不要输出任何其他说明。"
)

# 信息初始化：固定文稿 + 原始资料 -> 灵活文稿（专题深挖，JSON 数组）
FLEX_BUILD_PROMPT = (
    "你是一位面试准备助手。下面给出求职者的固定文稿和原始资料。\n"
    "请针对面试中可能被追问的技术细节，生成 3~8 篇「灵活文稿」。\n"
    "每篇聚焦一个主题，例如：某项目的技术实现细节、遇到的关键问题与解决过程、"
    "某项核心技术的深入理解、团队协作与角色贡献等。\n"
    "输出严格的 JSON 数组，不要输出任何其他文字或 Markdown 代码块标记：\n"
    '[{"title": "主题标题", "keywords": ["关键词1", "关键词2"], '
    '"content": "正文（500 字以内，口语化要点，含可直接引用的细节和数据）"}]\n'
    "要求：\n"
    "1. 每篇 keywords 5~8 个，覆盖面试官可能的不同问法（技术名、项目名、场景词）；\n"
    "2. 不要编造资料中没有的经历或数据；\n"
    "3. 各篇主题互不重复。"
)

REVIEW_PROMPT = (
    "你是一位面试复盘助手。下面给出一场面试的完整记录"
    "（面试官提问、候选人口述回答、AI 助手当时给出的建议）。\n"
    "请输出一份「面试复盘要点」Markdown 文稿，结构如下：\n"
    "## 本场问题清单（按主题归类，列出面试官实际问过的问题）\n"
    "## 回答质量点评（哪些回答到位、哪些含糊或遗漏要点）\n"
    "## 资料补充建议（哪些问题现有资料不足以支撑，建议补充什么素材）\n"
    "要求：\n"
    "1. 只基于记录内容总结，不要编造；\n"
    "2. 语言精炼，总长度 1200 字以内；\n"
    "3. 「资料补充建议」要具体可操作，方便后续直接补充进资料库。"
)

# 一键优化资料库：复盘 + 现有文稿 -> 文稿增改 + 宏观提示词建议（JSON）
REVIEW_APPLY_PROMPT = (
    "你是一位面试资料库优化助手。下面给出：最近一次面试复盘、候选人的固定文稿、"
    "现有灵活文稿索引（标题+关键词）。\n"
    "请根据复盘中的「资料补充建议」优化资料库，输出严格的 JSON 对象，"
    "不要输出任何其他文字或 Markdown 代码块标记：\n"
    '{"flex_updates": [{"title": "与现有文稿完全相同的标题", "keywords": [...], '
    '"content": "更新后的正文（500 字以内）"}],\n'
    ' "flex_additions": [{"title": "新主题标题", "keywords": [...], '
    '"content": "正文（500 字以内）"}],\n'
    ' "prompt_suggestion": "对面试回答风格的宏观改进建议（100 字以内）"}\n'
    "要求：\n"
    "1. 只依据复盘和现有资料，不要编造经历或数据；\n"
    "2. flex_updates 仅当某篇现有文稿确实需要补充/修正时使用，title 必须与索引中的"
    "标题完全一致；新主题放 flex_additions；\n"
    "3. prompt_suggestion 只写宏观层面的回答结构建议（如「分点不超过 3 个」"
    "「按 STAR 结构组织项目回答」），不要写具体知识点，没有可写的就填空字符串；\n"
    "4. 我会同时给出「现有改进要点」。prompt_suggestion 请输出**合并后的精简版**："
    "保留仍然适用的旧要点、吸收本次新建议、删除已过时或互相矛盾的条目，"
    "总长不超过 150 字；\n"
    "5. 没有需要更新/新增的文稿时对应数组留空。"
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
    "thinking": True,                    # 默认开启思考模式（答题/复盘/资料初始化）
    "qa_thinking": False,                # 问答/面试独立思考开关：默认关，实时场景低延迟优先
    "hotkey": "Ctrl+Alt+Q",              # 全局触发识别的快捷键
    "font_size": 14,                     # 答案区字号（px）
    "win_size": None,                    # 记住窗口大小 [w, h]
    "immersive_mode": False,             # 沉浸式：问答/面试时鼠标离开窗口自动只留答案区
    "stealth_compat": False,             # Win10 2004 兼容隐身：禁用半透明分层样式（需重启）
    "session_autosave": True,            # 持续优化：面试结束后自动保存场次记录并生成复盘
    "inject_review": True,               # 面试上下文注入复盘要点（interview_review.md）
    "prompt_improvements": "",           # 复盘给出的宏观提示词改进（用户级，不随预设）
    "ui_bg_opacity": 0.80,               # UI 区域（标题栏/按钮区底板）背景不透明度 0~1
    "answer_bg_opacity": 0.05,           # 答案区背景不透明度 0~1（白色叠加层）
    "ui_bg_color": "#181b22",            # UI 底板颜色
    "ui_text_color": "#e8eaf0",          # UI 字体颜色（标题/状态/按钮文字统一派生）
    "ui_text_opacity": 1.0,              # UI 字体不透明度 0~1
    "answer_bg_color": "#ffffff",        # 答案区背景颜色
    "answer_text_color": "#f2f4f8",      # 答案字体颜色
    "answer_text_opacity": 1.0,          # 答案字体不透明度 0~1
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
    "interview_auto_answer": True,         # 面试模式：面试官静默 2 秒自动作答
    "resume_name": "",                     # 已加载简历的文件名（仅用于显示）
    "resume_text": "",                     # 简历解析后的纯文本
}


def config_dir() -> str:
    if getattr(sys, "frozen", False):
        # 打包版：exe 同级目录会随重装/覆盖安装/重打包被清空，
        # 配置放到用户级稳定目录 %LOCALAPPDATA%\答题助手\，并从旧位置迁移一次。
        root = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "答题助手")
        old = os.path.join(os.path.dirname(sys.executable), "config.json")
        new = os.path.join(root, "config.json")
        if not os.path.exists(new) and os.path.exists(old):
            try:
                os.makedirs(root, exist_ok=True)
                import shutil
                shutil.copy2(old, new)
            except OSError:
                pass
        return root
    return os.path.dirname(os.path.abspath(__file__))


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


class AppConfig:
    def __init__(self, data: dict):
        self.data = dict(DEFAULTS)
        self.data.update(data or {})
        self._migrate()

    def _migrate(self):
        """老版本配置迁移：配置里存的提示词若仍是 v1.x 旧默认原文，
        升级为当前默认（用户自定义过的不动）。"""
        if self.data.get("interview_prompt") == _INTERVIEW_PROMPT_V1:
            self.data["interview_prompt"] = INTERVIEW_PROMPT

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
