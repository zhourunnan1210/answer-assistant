# -*- coding: utf-8 -*-
"""多模态大模型调用：支持 OpenAI 兼容格式与 Anthropic 格式，含模型列表获取与思考模式。"""
import base64

import requests

from config import (DEFAULT_PROMPT, FLEX_BUILD_PROMPT, INTERVIEW_PROMPT,
                    PROFILE_BUILD_PROMPT, QA_PROMPT, REVIEW_APPLY_PROMPT,
                    REVIEW_PROMPT)

OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"
ANTHROPIC_DEFAULT_BASE = "https://api.anthropic.com"


class LlmError(Exception):
    pass


# 自动作答模式专用提示词：要求模型返回选项/下一题按钮的位置（归一化坐标）
AUTO_PROMPT = (
    "你是一个网课自动答题助手。图片是一道网课题目（含题干和选项）。\n"
    "请只输出一个 JSON 对象，不要输出任何其他文字或 Markdown 代码块标记，格式：\n"
    '{"answer": "答案文本", "answer_box": [x1, y1, x2, y2], "next_box": [x1, y1, x2, y2] 或 null}\n'
    "字段说明：\n"
    "- answer：选择题写选项字母+选项内容，判断题写 对/错，填空题写答案；\n"
    "- answer_box：你认为正确的那个选项（含选项字母和文字的可点击条目）在图片中的包围框；\n"
    "- next_box：\"下一题\"\"提交\"等翻页按钮的包围框，图片中没有则为 null；\n"
    "- 坐标为相对图片宽高的比例（0~1），左上角为 (0,0)。"
)


def _err_body(resp: requests.Response) -> str:
    return resp.text[:400] if resp.text else "(无响应体)"


def _check(resp: requests.Response):
    if resp.status_code != 200:
        raise LlmError(f"HTTP {resp.status_code}: {_err_body(resp)}")


# ---------------------------------------------------------------- 对话调用

def _post_openai(url: str, api_key: str, body: dict) -> requests.Response:
    """POST chat/completions，带两类自动降级重试：
    1) 400 提示 temperature 不合法（推理模型常见）→ 移除 temperature 重试；
    2) 400 提示 max_tokens 超限 → 逐次减半重试（16384→8192→…→1024）。"""
    headers = {"Authorization": f"Bearer {api_key}",
               "Content-Type": "application/json"}

    def _post(b):
        return requests.post(url, headers=headers, json=b, timeout=120)

    resp = _post(body)
    if (resp.status_code == 400 and "temperature" in resp.text.lower()
            and "temperature" in body):
        body = dict(body)
        body.pop("temperature")
        resp = _post(body)
    while (resp.status_code == 400 and "max_tokens" in resp.text.lower()
           and body.get("max_tokens", 0) > 1024):
        body = dict(body)
        body["max_tokens"] //= 2
        resp = _post(body)
    return resp


def _openai_chat(cfg, content_parts, thinking: bool) -> str:
    base = (cfg["base_url"] or OPENAI_DEFAULT_BASE).rstrip("/")
    url = base + "/chat/completions"
    # 不传过小 max_tokens：显式给宽裕值 16384，服务端拒收时自动逐级减半
    payload = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": content_parts}],
        "max_tokens": 16384,
        "temperature": 0.2,
    }
    # 思考模式参数各家不同，按 Kimi 格式 -> 通义格式 -> 关闭思考 自动降级
    attempts = ([{"thinking": {"type": "enabled"}},
                 {"enable_thinking": True},
                 {}] if thinking else [{}])
    last_err = "未知错误"
    for extra in attempts:
        body = dict(payload)
        body.update(extra)
        resp = _post_openai(url, cfg["api_key"], body)
        if resp.status_code == 200:
            data = resp.json()
            try:
                choice = data["choices"][0]
                msg = choice.get("message") or {}
                content = (msg.get("content") or "").strip()
            except Exception:
                raise LlmError(f"无法解析响应: {str(data)[:300]}")
            if not content:
                if choice.get("finish_reason") == "length":
                    raise LlmError("模型输出被截断（finish_reason=length），答案未生成，请重试")
                raise LlmError("模型返回了空答案，请重试")
            return content
        last_err = f"HTTP {resp.status_code}: {_err_body(resp)}"
        if resp.status_code == 400 and extra:
            continue  # 思考参数不兼容，降级重试
        raise LlmError(last_err)
    raise LlmError(last_err)


def _anthropic_chat(cfg, content_parts, thinking: bool) -> str:
    base = (cfg["base_url"] or ANTHROPIC_DEFAULT_BASE).rstrip("/")
    url = base + "/messages" if base.endswith("/v1") else base + "/v1/messages"
    # Anthropic API 强制要求 max_tokens，给一个远超答案所需的宽裕值
    payload = {
        "model": cfg["model"],
        "max_tokens": 16384,
        "messages": [{"role": "user", "content": content_parts}],
    }
    if thinking:
        payload["thinking"] = {"type": "enabled", "budget_tokens": 2048}
    headers = {"x-api-key": cfg["api_key"],
               "anthropic-version": "2023-06-01",
               "Content-Type": "application/json"}
    for attempt in range(2 if thinking else 1):
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code == 200:
            data = resp.json()
            try:
                return "".join(b.get("text", "") for b in data["content"]
                               if b.get("type") == "text").strip()
            except Exception:
                raise LlmError(f"无法解析响应: {str(data)[:300]}")
        if (resp.status_code == 400 and attempt == 0 and thinking
                and "thinking" in resp.text.lower()):
            payload.pop("thinking", None)  # 该端点不支持思考模式，降级重试
            continue
        _check(resp)
    raise LlmError("请求失败")


def ask_vision(cfg: dict, png_bytes: bytes) -> str:
    """把题目截图发给多模态模型，返回答案文本。cfg 为 config 字典快照。"""
    if not cfg.get("api_key"):
        raise LlmError("未配置 API Key，请先在设置中填写。")
    if not cfg.get("model"):
        raise LlmError("未配置模型名称，请先在设置中填写。")

    b64 = base64.b64encode(png_bytes).decode("ascii")
    prompt = cfg.get("prompt") or DEFAULT_PROMPT
    thinking = bool(cfg.get("thinking", True))

    if cfg.get("provider") == "anthropic":
        parts = [
            {"type": "image",
             "source": {"type": "base64", "media_type": "image/png", "data": b64}},
            {"type": "text", "text": prompt},
        ]
        return _anthropic_chat(cfg, parts, thinking)
    else:
        parts = [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]
        return _openai_chat(cfg, parts, thinking)


def ask_text(cfg: dict, question: str) -> str:
    """问答助手：纯文本对话。使用独立的 qa_prompt（口语化结构化回答）。"""
    if not cfg.get("api_key"):
        raise LlmError("未配置 API Key，请先在设置中填写。")
    if not cfg.get("model"):
        raise LlmError("未配置模型名称，请先在设置中填写。")
    prompt = cfg.get("qa_prompt") or QA_PROMPT
    content = f"{prompt}\n\n以下是会议中语音识别出的讲话内容：\n{question}"
    parts = [{"type": "text", "text": content}]
    thinking = bool(cfg.get("thinking", True))
    if cfg.get("provider") == "anthropic":
        return _anthropic_chat(cfg, parts, thinking)
    return _openai_chat(cfg, parts, thinking)


def _plain_chat(cfg: dict, content: str) -> str:
    """纯文本单轮对话（不校验配置，调用方负责）。"""
    parts = [{"type": "text", "text": content}]
    thinking = bool(cfg.get("thinking", True))
    if cfg.get("provider") == "anthropic":
        return _anthropic_chat(cfg, parts, thinking)
    return _openai_chat(cfg, parts, thinking)


def ask_interview(cfg: dict, question: str, convo: str = "") -> str:
    """面试辅助：资料库上下文 + 对话记录 + 面试官讲话 -> 口语化回答。"""
    if not cfg.get("api_key"):
        raise LlmError("未配置 API Key，请先在设置中填写。")
    if not cfg.get("model"):
        raise LlmError("未配置模型名称，请先在设置中填写。")
    return _plain_chat(cfg, build_interview_content(cfg, question, convo))


def build_interview_content(cfg: dict, question: str, convo: str = "") -> str:
    """组装面试问答上下文（纯函数，便于测试）：
    面试提示词 + 固定文稿 + 灵活文稿索引 + 命中专题 + 对话记录 + 本轮问题。"""
    import profile_store as ps
    fixed = ps.load_fixed() or (cfg.get("resume_text") or "").strip()
    if not fixed:
        raise LlmError("资料库为空，请先在设置的「面试助手」分组中"
                       "上传资料并生成固定文稿。")
    prompt = cfg.get("interview_prompt") or INTERVIEW_PROMPT
    improvements = (cfg.get("prompt_improvements") or "").strip()
    if improvements:
        prompt += "\n\n【复盘改进要点】\n" + improvements
    parts = [prompt, "【固定文稿】\n" + fixed[:ps.FIXED_MAX_CHARS]]
    docs = ps.load_flex()
    if docs:
        parts.append("【专题资料索引】\n" + ps.flex_index(docs))
        for d in ps.retrieve(question, docs):
            body = (d.get("content") or "")[:ps.FLEX_DOC_MAX_CHARS]
            parts.append(f"【专题资料：{d.get('title') or '未命名'}】\n{body}")
    if convo:
        parts.append("【面试对话记录】\n" + convo[-ps.CONVO_MAX_CHARS:])
    if cfg.get("inject_review", True):
        review = ps.load_review()
        if review:
            parts.append("【面试复盘要点】\n" + review[:ps.REVIEW_MAX_CHARS])
    parts.append("【面试官最新讲话】\n" + question)
    return "\n\n".join(parts)


def generate_review(cfg: dict, session_text: str) -> str:
    """面试场次记录 -> LLM 复盘要点（Markdown）。"""
    if not cfg.get("api_key"):
        raise LlmError("未配置 API Key，请先在设置中填写。")
    if not cfg.get("model"):
        raise LlmError("未配置模型名称，请先在设置中填写。")
    import profile_store as ps
    content = (REVIEW_PROMPT + "\n\n【面试记录】\n"
               + session_text[:ps.SESSION_MAX_CHARS])
    return _plain_chat(cfg, content)


def apply_review(cfg: dict) -> dict:
    """一键优化资料库：复盘 + 固定文稿 + 灵活文稿索引 ->
    {"flex_updates": [...], "flex_additions": [...], "prompt_suggestion": str}"""
    if not cfg.get("api_key"):
        raise LlmError("未配置 API Key，请先在设置中填写。")
    if not cfg.get("model"):
        raise LlmError("未配置模型名称，请先在设置中填写。")
    import profile_store as ps
    review = ps.load_review()
    if not review:
        raise LlmError("还没有面试复盘。先完成一场面试（或手动编辑复盘）。")
    fixed = ps.load_fixed() or (cfg.get("resume_text") or "")
    docs = ps.load_flex()
    content = (REVIEW_APPLY_PROMPT + "\n\n【面试复盘】\n" + review[:6000]
               + "\n\n【固定文稿】\n" + fixed[:4000]
               + "\n\n【灵活文稿索引】\n" + (ps.flex_index(docs) or "（空）"))
    out = _plain_chat(cfg, content)
    result = _parse_docs_json_object(out)
    for key in ("flex_updates", "flex_additions"):
        result.setdefault(key, [])
        result[key] = [d for d in result[key]
                       if isinstance(d, dict) and d.get("content")]
    result.setdefault("prompt_suggestion", "")
    return result


def _parse_docs_json_object(out: str) -> dict:
    """从模型回复中解析 JSON 对象（容忍代码块/前后杂质）。"""
    import json as _json
    import re as _re
    m = _re.search(r"\{.*\}", out, _re.S)
    if not m:
        raise LlmError("未能从模型回复中解析出结果，请重试。原始回复：" + out[:200])
    try:
        obj = _json.loads(m.group(0))
    except ValueError:
        raise LlmError("模型回复的 JSON 格式有误，请重试。原始回复：" + out[:200])
    if not isinstance(obj, dict):
        raise LlmError("模型回复格式有误，请重试。")
    return obj


# ---------------------------------------------------------------- 信息初始化

def build_fixed_profile(cfg: dict, raw_texts: list) -> str:
    """原始资料 [(文件名, 文本)] -> LLM 整理归纳的固定文稿。"""
    if not cfg.get("api_key"):
        raise LlmError("未配置 API Key，请先在设置中填写。")
    if not cfg.get("model"):
        raise LlmError("未配置模型名称，请先在设置中填写。")
    if not raw_texts:
        raise LlmError("请先上传简历/个人资料文件。")
    blob = "\n\n".join(f"【{name}】\n{text}" for name, text in raw_texts)
    return _plain_chat(cfg, PROFILE_BUILD_PROMPT + "\n\n" + blob[:24000])


def build_flexible_docs(cfg: dict, fixed_text: str, raw_texts: list) -> list:
    """固定文稿 + 原始资料 -> 3~8 篇灵活文稿（JSON 解析 + 校验）。"""
    if not cfg.get("api_key"):
        raise LlmError("未配置 API Key，请先在设置中填写。")
    if not cfg.get("model"):
        raise LlmError("未配置模型名称，请先在设置中填写。")
    if not (fixed_text or "").strip():
        raise LlmError("请先生成或填写固定文稿。")
    blob = "\n\n".join(f"【{name}】\n{text}" for name, text in raw_texts)
    content = (FLEX_BUILD_PROMPT + "\n\n【固定文稿】\n" + fixed_text[:12000]
               + ("\n\n【原始资料】\n" + blob[:20000] if blob else ""))
    out = _plain_chat(cfg, content)
    docs = _parse_docs_json(out)
    if not docs:
        raise LlmError("未能从模型回复中解析出灵活文稿，请重试。原始回复："
                       + out[:200])
    for i, d in enumerate(docs):
        d["id"] = i + 1
        d.setdefault("title", f"专题 {i + 1}")
        d.setdefault("keywords", [])
    return docs


def _parse_docs_json(text: str) -> list:
    """从模型输出中提取 JSON 数组并做基本校验。"""
    import json
    import re
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("["), text.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        data = json.loads(text[start:end + 1])
    except Exception:
        return []
    return [d for d in data
            if isinstance(d, dict) and (d.get("content") or "").strip()]


# ---------------------------------------------------------------- 语音识别（ASR）

def _asr_config(cfg: dict):
    """返回 (base_url, api_key, model)。asr_use_same_key 时复用答题模型的服务商。"""
    if cfg.get("asr_use_same_key"):
        base, key = cfg.get("base_url"), cfg.get("api_key")
    else:
        base, key = cfg.get("asr_base_url"), cfg.get("asr_api_key")
    base = (base or "").rstrip("/")
    model = cfg.get("asr_model") or "whisper-1"
    if not base:
        raise LlmError("未配置语音识别 Base URL，请在设置中填写。")
    if not key:
        raise LlmError("未配置语音识别 API Key，请在设置中填写。")
    return base, key, model


def asr_use_local(cfg: dict) -> bool:
    """当前配置的语音识别来源是否为本地模型。"""
    return cfg.get("asr_source", "local") == "local"


def transcribe_audio(cfg: dict, wav_bytes: bytes) -> str:
    """语音识别入口：按 asr_source 分流到本地 SenseVoice 或云端 Whisper 兼容 API。

    本地模式（默认）：sherpa-onnx 离线推理，零网络、免 Key、毫秒级响应。
    云端模式：POST {base}/audio/transcriptions（multipart），支持 OpenAI
    whisper-1、SiliconFlow 的 SenseVoice 等。免费档 ASR 服务常有冷启动/排队
    导致的超时，网络层错误自动重试 3 次，单次请求超时压到 25s。"""
    if asr_use_local(cfg):
        import asr_local
        try:
            return asr_local.transcribe_local(wav_bytes)
        except asr_local.LocalAsrError as e:
            raise LlmError(str(e))
    import time as _time
    base, key, model = _asr_config(cfg)
    last_err = "未知错误"
    for attempt in range(3):
        try:
            resp = requests.post(
                base + "/audio/transcriptions",
                headers={"Authorization": f"Bearer {key}"},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={"model": model},
                timeout=25)
            if resp.status_code >= 500:  # 服务端错误也重试
                last_err = f"HTTP {resp.status_code}: {_err_body(resp)}"
                _time.sleep(1 + attempt)
                continue
            _check(resp)
            try:
                return (resp.json().get("text") or "").strip()
            except Exception:
                raise LlmError(f"无法解析识别结果: {resp.text[:200]}")
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as e:
            last_err = f"{type(e).__name__}: {e}"
            _time.sleep(1 + attempt)
    raise LlmError(f"语音识别服务连接失败（已自动重试 3 次）：{last_err}")


def test_asr(cfg: dict) -> str:
    """验证语音识别链路：本地模式加载模型并识别测试音；云端模式发送 0.8 秒测试音。"""
    from audio_capture import test_tone_wav
    if asr_use_local(cfg):
        import asr_local
        if not asr_local.model_ready():
            raise LlmError("未找到本地语音模型（" + asr_local.model_dir() + "）")
        import time as _t
        t0 = _t.time()
        asr_local.warmup()
        load_s = _t.time() - t0
        t0 = _t.time()
        asr_local.transcribe_local(test_tone_wav())
        infer_s = _t.time() - t0
        return f"本地模型就绪（加载 {load_s:.1f}s，推理 {infer_s:.2f}s，完全离线）"
    text = transcribe_audio(cfg, test_tone_wav())
    return text or "服务连通正常（测试音无语音内容，识别结果为空）"


def test_connection(cfg: dict) -> str:
    """纯文本连通性测试，返回模型回复的前 80 个字符。"""
    if not cfg.get("api_key"):
        raise LlmError("未填写 API Key")
    if not cfg.get("model"):
        raise LlmError("未填写模型名称")
    parts = [{"type": "text", "text": "请只回复：OK"}]
    thinking = bool(cfg.get("thinking", True))
    if cfg.get("provider") == "anthropic":
        out = _anthropic_chat(cfg, parts, thinking)
    else:
        out = _openai_chat(cfg, parts, thinking)
    return out[:80]


# ---------------------------------------------------------------- 模型列表

def fetch_models(cfg: dict) -> list:
    """拉取供应商模型列表，返回 [{id, image, reasoning, context_length}]。
    image/reasoning 为 True/False/None（供应商未提供该信息时为 None）。"""
    if not cfg.get("api_key"):
        raise LlmError("请先填写 API Key")

    if cfg.get("provider") == "anthropic":
        base = (cfg.get("base_url") or ANTHROPIC_DEFAULT_BASE).rstrip("/")
        url = base + "/models" if base.endswith("/v1") else base + "/v1/models"
        resp = requests.get(url, headers={
            "x-api-key": cfg["api_key"],
            "anthropic-version": "2023-06-01"}, timeout=30)
        _check(resp)
        data = resp.json().get("data", [])
        return [{"id": m.get("id"), "image": None,
                 "reasoning": None, "context_length": m.get("context_length")}
                for m in data if m.get("id")]

    base = (cfg.get("base_url") or OPENAI_DEFAULT_BASE).rstrip("/")
    resp = requests.get(base + "/models", headers={
        "Authorization": f"Bearer {cfg['api_key']}"}, timeout=30)
    _check(resp)
    data = resp.json().get("data", [])
    return [{"id": m.get("id"),
             "image": m.get("supports_image_in"),
             "reasoning": m.get("supports_reasoning"),
             "context_length": m.get("context_length")}
            for m in data if m.get("id")]
