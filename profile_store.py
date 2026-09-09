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


# ---------------------------------------------------------------- 面试场次记录与复盘

REVIEW_MAX_CHARS = 1500    # 注入上下文的复盘要点上限
SESSION_MAX_CHARS = 12000  # 生成复盘时读取的场次记录上限


def sessions_dir() -> str:
    return os.path.join(base_dir(), "sessions")


def review_path() -> str:
    return os.path.join(base_dir(), "interview_review.md")


def save_session(lines: list) -> str:
    """把一场面试的记录（面试官/我/助手建议，按时间序）写成 md 文件，
    返回文件路径。文件名带时间戳，多场并存。"""
    import datetime
    os.makedirs(sessions_dir(), exist_ok=True)
    name = datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".md"
    path = os.path.join(sessions_dir(), name)
    body = "\n\n".join(l.strip() for l in lines if l and l.strip())
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# 面试记录 {datetime.datetime.now():%Y-%m-%d %H:%M}\n\n{body}\n")
    return path


def load_review() -> str:
    try:
        with open(review_path(), "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_review(text: str):
    """保存复盘：reviews/ 按时间戳归档历史，interview_review.md 永远是最新一场。"""
    import datetime
    os.makedirs(reviews_dir(), exist_ok=True)
    with open(review_path(), "w", encoding="utf-8") as f:
        f.write(text.strip())
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = os.path.join(reviews_dir(), stamp + ".md")
    i = 1
    while os.path.exists(path):  # 同一秒保存多次时加序号
        path = os.path.join(reviews_dir(), f"{stamp}_{i}.md")
        i += 1
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.strip())


def reviews_dir() -> str:
    return os.path.join(base_dir(), "reviews")


def merge_flex(docs: list, updates: list, additions: list) -> list:
    """按标题合并复盘优化结果：同标题覆盖更新，新主题追加。
    updates 里找不到同标题的自动转为追加，宁多勿丢。"""
    docs = [dict(d) for d in docs]
    by_title = {d.get("title"): d for d in docs}
    for u in updates:
        t = u.get("title")
        if t in by_title:
            by_title[t].update(
                {k: v for k, v in u.items() if k in ("keywords", "content") and v})
        else:
            additions.append(u)
    import time as _t
    for a in additions:
        d = {"id": f"review-{int(_t.time()*1000)}",
             "title": a.get("title") or "未命名",
             "keywords": a.get("keywords") or [],
             "content": a.get("content") or ""}
        docs.append(d)
        by_title[d["title"]] = d
    return docs
