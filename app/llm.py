"""OpenAI 兼容对话客户端：一个实现通吃 DeepSeek / 硅基流动 / Kimi / 智谱 / 通义 / OpenRouter / Ollama 及任意自定义平台。
错误统一翻译成中文排查指引。"""
import json
from typing import AsyncGenerator, Optional

import httpx


class LLMError(Exception):
    """带中文排查指引的对话接口错误。"""


class ReasoningLengthError(LLMError):
    """推理模型把 max_tokens 全部耗在思考上、没来得及输出正文。"""


def _friendly_status(code: int, body: str) -> str:
    detail = body[:300] if body else ""
    if code == 401:
        return f"API Key 无效或未填（401）。请到「设置」检查 Key 是否复制完整、是否属于所选平台。平台返回：{detail}"
    if code == 402:
        return f"账户余额不足（402）。请到平台充值后再试。平台返回：{detail}"
    if code == 404:
        return f"接口地址或模型名不对（404）。请检查 Base URL 是否以 /v1 结尾、模型名是否拼写正确。平台返回：{detail}"
    if code == 422 or code == 400:
        return f"请求参数被平台拒绝（{code}）。常见原因：模型名不存在、该模型不支持当前参数。平台返回：{detail}"
    if code == 429:
        return f"触发平台限流（429）。请稍等几秒重试，或检查账户额度/并发限制。平台返回：{detail}"
    if code >= 500:
        return f"平台服务端临时故障（{code}）。请稍后重试。平台返回：{detail}"
    return f"平台返回异常（{code}）：{detail}"


def _headers(cfg: dict) -> dict:
    h = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        h["Authorization"] = f"Bearer {cfg['api_key']}"
    return h


def _url(cfg: dict) -> str:
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise LLMError("未配置 Base URL。请到「设置」选择平台或填写接口地址。")
    if not base.endswith("/chat/completions"):
        base = base + "/chat/completions"
    return base


def _model(cfg: dict) -> str:
    model = (cfg.get("model") or "").strip()
    if not model:
        raise LLMError("未配置模型名称。请到「设置」点「获取模型列表」选择一个模型。")
    return model


async def _chat_once(cfg: dict, payload: dict, timeout: float) -> str:
    last_err: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                r = await client.post(_url(cfg), headers=_headers(cfg), json=payload)
            if r.status_code != 200:
                raise LLMError(_friendly_status(r.status_code, r.text))
            data = r.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            if not content.strip():
                if message.get("reasoning_content") and choice.get("finish_reason") == "length":
                    raise ReasoningLengthError("推理模型把 max_tokens 耗在了思考上")
                raise LLMError(f"平台返回了空内容。原始返回：{json.dumps(data, ensure_ascii=False)[:300]}")
            return content
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            last_err = e
            if attempt == 1:
                break
    name = type(last_err).__name__ if last_err else ""
    raise LLMError(f"连接平台失败（{name}）。请检查服务器网络、Base URL 是否正确、平台是否可访问。{last_err}")


async def chat(cfg: dict, messages: list, *, max_tokens: int = 2000,
               temperature: Optional[float] = None, timeout: float = 240.0) -> str:
    """一次性对话（非流式），供生成流水线各阶段使用。
    推理模型可能把输出额度耗在思考上，此时自动放大 max_tokens 重试（最多 32000）。"""
    payload = {"model": _model(cfg), "messages": messages, "max_tokens": max_tokens, "stream": False}
    payload["temperature"] = cfg.get("temperature", 0.8) if temperature is None else temperature
    budget = max_tokens
    for _ in range(3):
        try:
            return await _chat_once(cfg, payload, timeout)
        except ReasoningLengthError:
            if budget >= 32000:
                raise LLMError("模型的推理过程超长，32000 token 内仍未能给出正文。请换一个非推理模型（如 deepseek-v3 系列）再试。")
            budget = min(budget * 4, 32000)
            payload["max_tokens"] = budget


async def _stream_core(cfg: dict, payload: dict, timeout: float):
    """打开流式连接解析 SSE：逐段 yield {"kind","text"}（kind: reasoning|content），
    结束时 yield {"kind":"done","finish","content","think_len"}。网络错误自动重试一次（重试前发 reset）。"""
    last_err: Exception | None = None
    for attempt in range(2):
        if attempt:
            yield {"kind": "reset", "text": ""}
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", _url(cfg), headers=_headers(cfg), json=payload) as r:
                    if r.status_code != 200:
                        body = (await r.aread()).decode("utf-8", "ignore")
                        raise LLMError(_friendly_status(r.status_code, body))
                    content_parts: list[str] = []
                    think_len = 0
                    finish = None
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data or data == "[DONE]":
                            continue
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choice = (chunk.get("choices") or [{}])[0]
                        delta = choice.get("delta") or {}
                        rc = delta.get("reasoning_content")
                        if rc:
                            think_len += len(rc)
                            yield {"kind": "reasoning", "text": rc}
                        pc = delta.get("content")
                        if pc:
                            content_parts.append(pc)
                            yield {"kind": "content", "text": pc}
                        if choice.get("finish_reason"):
                            finish = choice["finish_reason"]
                    yield {"kind": "done", "finish": finish,
                           "content": "".join(content_parts), "think_len": think_len}
                    return
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            last_err = e
            if attempt == 1:
                break
    raise LLMError(f"连接平台失败（{type(last_err).__name__}）。请检查服务器网络、Base URL 是否正确、平台是否可访问。{last_err}")


async def stream_collect(cfg: dict, messages: list, *, max_tokens: int = 2000,
                         temperature: Optional[float] = None, timeout: float = 300.0,
                         on_delta=None) -> str:
    """流式请求并收集完整正文，供生成流水线使用。on_delta(kind, text) 为异步回调，
    实时转发思维链与输出；推理模型耗尽输出额度时自动放大 max_tokens 重试。"""
    payload = {"model": _model(cfg), "messages": messages, "max_tokens": max_tokens, "stream": True}
    payload["temperature"] = cfg.get("temperature", 0.8) if temperature is None else temperature
    budget = max_tokens
    for _ in range(3):
        async for ev in _stream_core(cfg, payload, timeout):
            if ev["kind"] == "done":
                if ev["content"].strip():
                    return ev["content"]
                if ev["finish"] == "length" and ev["think_len"] > 0:
                    break  # 思考耗尽额度 → 放大重试
                raise LLMError("平台返回了空内容（流式）。请重试或换个模型。")
            if on_delta:
                await on_delta(ev["kind"], ev["text"])
        else:
            raise LLMError("流式响应异常中断。请重试。")
        if budget >= 32000:
            raise LLMError("模型的推理过程超长，32000 token 内仍未能给出正文。请换一个非推理模型（如 deepseek-v3 系列）再试。")
        budget = min(budget * 4, 32000)
        payload["max_tokens"] = budget
        if on_delta:
            await on_delta("reset", "")
    raise LLMError("生成失败，请重试。")


async def chat_stream(cfg: dict, messages: list, *, max_tokens: int = 2000,
                      temperature: Optional[float] = None, timeout: float = 240.0) -> AsyncGenerator[dict, None]:
    """流式对话，供 AI 主持逐字输出使用。逐段 yield {"kind","text"}（kind: reasoning|content|reset）。"""
    payload = {"model": _model(cfg), "messages": messages, "max_tokens": max_tokens, "stream": True}
    payload["temperature"] = cfg.get("temperature", 0.8) if temperature is None else temperature
    budget = max_tokens
    for _ in range(3):
        done = None
        async for ev in _stream_core(cfg, payload, timeout):
            if ev["kind"] == "done":
                done = ev
                break
            yield {"kind": ev["kind"], "text": ev["text"]}
        if done and done["content"].strip():
            return
        if done and done["finish"] == "length" and done["think_len"] > 0:
            if budget >= 32000:
                raise LLMError("主持人模型的推理过程超长，未能给出回答。请换一个非推理模型再试。")
            budget = min(budget * 4, 32000)
            payload["max_tokens"] = budget
            yield {"kind": "reset", "text": ""}
            continue
        raise LLMError("平台返回了空内容（流式）。请重试。")


async def ping(cfg: dict) -> float:
    """「测试连接」：发一个极小请求，返回耗时秒数；失败抛 LLMError。"""
    import time
    t0 = time.monotonic()
    await chat(cfg, [{"role": "user", "content": "回复：OK"}], max_tokens=512, temperature=0, timeout=60)
    return round(time.monotonic() - t0, 2)


async def list_models(cfg: dict, timeout: float = 30.0) -> list[str]:
    """拉取平台的模型列表（OpenAI 兼容 GET /models）。失败抛带中文指引的 LLMError。"""
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise LLMError("请先填写 Base URL（接口地址）")
    url = base if base.endswith("/models") else base + "/models"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=_headers(cfg))
    except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
        raise LLMError(f"无法连接平台（{type(e).__name__}）。请检查 Base URL 是否正确、服务器能否访问该平台。{e}")
    if r.status_code == 404:
        raise LLMError("该平台不支持自动获取模型列表（/models 返回 404）。请到平台文档查一下模型名，手动填写即可。")
    if r.status_code != 200:
        raise LLMError(_friendly_status(r.status_code, r.text))
    try:
        data = r.json()
    except Exception:
        raise LLMError("平台返回的不是标准 JSON，可能不支持 /models 接口，请手动填写模型名。")
    items = data.get("data") if isinstance(data, dict) else data
    ids: list[str] = []
    if isinstance(items, list):
        for it in items:
            mid = it.get("id") if isinstance(it, dict) else it
            if isinstance(mid, str) and mid:
                ids.append(mid)
    if not ids:
        raise LLMError("平台未返回任何模型，请手动填写模型名。")
    return sorted(set(ids))
