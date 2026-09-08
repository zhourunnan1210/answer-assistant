# -*- coding: utf-8 -*-
"""多模态大模型调用：支持 OpenAI 兼容格式与 Anthropic 格式，含模型列表获取与思考模式。"""
import base64

import requests

from config import DEFAULT_PROMPT

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
