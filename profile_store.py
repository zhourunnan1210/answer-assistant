# -*- coding: utf-8 -*-
"""个人资料库：固定文稿 + 灵活文稿 + 原始资料，供面试辅助组装上下文。

存储位置：打包版为用户级稳定目录 %LOCALAPPDATA%\\答题助手\\profile\\
（exe 同级目录会随重装/重打包被清空，旧位置会自动迁移一次）；
源码运行为脚本同目录的 profile/ 文件夹（可用环境变量 PROFILE_DIR 覆盖，
便于测试）：
  fixed_profile.md    固定文稿（个人介绍 + 过往项目介绍），可手动编辑
  flexible_docs.json  灵活文稿 [{id, title, keywords, content}]
  raw/                上传的原始文件备份（可追溯）
"""
import json
import os
import shutil
import sys

FIXED_MAX_CHARS = 8000     # 注入上下文的固定文稿上限
FLEX_DOC_MAX_CHARS = 3000  # 注入上下文的单篇灵活文稿上限
FLEX_MAX_HITS = 2          # 单次最多注入的灵活文稿篇数
CONVO_MAX_CHARS = 5000     # 注入上下文的对话记录上限（滚动窗口）


def base_dir() -> str:
    override = os.environ.get("PROFILE_DIR")
    if override:
        return override
    if getattr(sys, "frozen", False):
        new = os.path.join(
            os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"),
            "答题助手", "profile")
        old = os.path.join(os.path.dirname(sys.executable), "profile")
        if not os.path.exists(new) and os.path.isdir(old):
            try:
                os.makedirs(os.path.dirname(new), exist_ok=True)
                shutil.copytree(old, new)
            except OSError:
                pass
        return new
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "profile")


def fixed_path() -> str:
    return os.path.join(base_dir(), "fixed_profile.md")


def flex_path() -> str:
    return os.path.join(base_dir(), "flexible_docs.json")


def raw_dir() -> str:
    return os.path.join(base_dir(), "raw")


def load_fixed() -> str:
    try:
        with open(fixed_path(), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_fixed(text: str):
    os.makedirs(base_dir(), exist_ok=True)
    with open(fixed_path(), "w", encoding="utf-8") as f:
        f.write(text.strip())


def load_flex() -> list:
    try:
        with open(flex_path(), "r", encoding="utf-8") as f:
            docs = json.load(f)
        return [d for d in docs if isinstance(d, dict) and d.get("content")]
    except Exception:
        return []


def save_flex(docs: list):
    os.makedirs(base_dir(), exist_ok=True)
    with open(flex_path(), "w", encoding="utf-8") as f:
        json.dump(docs, f, ensure_ascii=False, indent=2)


def add_raw(src_path: str) -> str:
    """把上传的原始文件复制进 raw/（重名自动加序号），返回目标路径。"""
    os.makedirs(raw_dir(), exist_ok=True)
    name = os.path.basename(src_path)
    base, ext = os.path.splitext(name)
    dst = os.path.join(raw_dir(), name)
    i = 1
    while os.path.exists(dst):
        dst = os.path.join(raw_dir(), f"{base}_{i}{ext}")
        i += 1
    shutil.copy2(src_path, dst)
    return dst


def list_raw() -> list:
    try:
        return sorted(os.listdir(raw_dir()))
    except OSError:
        return []


def clear_raw():
    shutil.rmtree(raw_dir(), ignore_errors=True)


def read_raw_texts() -> list:
    """把 raw/ 下所有文件解析为 [(文件名, 文本)]，解析失败的跳过。"""
    import docparse
    out = []
    for name in list_raw():
        try:
            out.append((name, docparse.extract_text(
                os.path.join(raw_dir(), name))))
        except Exception:
            continue
    return out


# ---------------------------------------------------------------- 轻量检索

def _bigrams(s: str) -> set:
    s = "".join(s.split()).lower()
    return {s[i:i + 2] for i in range(len(s) - 1)}


def flex_index(docs: list) -> str:
    """灵活文稿索引（标题 + 关键词），每次提问随上下文发给 LLM。"""
    lines = []
    for d in docs:
        kw = "、".join(d.get("keywords") or [])
        lines.append(f"- {d.get('title') or '未命名'}（关键词：{kw}）")
    return "\n".join(lines)


def retrieve(question: str, docs: list, max_hits: int = FLEX_MAX_HITS) -> list:
    """关键词命中（权重高）+ 标题二元组重合打分，返回 top max_hits 篇。

    纯 Python 实现、零依赖、离线——灵活文稿数量少（3~8 篇），
    不需要向量检索。"""
    if not question or not docs:
        return []
    q_bg = _bigrams(question)
    scored = []
    for d in docs:
        score = 0.0
        for kw in (d.get("keywords") or []):
            if kw and kw in question:
                score += 3
        title_bg = _bigrams(d.get("title") or "")
        if title_bg and q_bg:
            score += 2 * len(title_bg & q_bg) / len(title_bg)
        scored.append((score, d))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [d for s, d in scored[:max_hits] if s > 0]
