"""生图渠道抽象：豆包/火山引擎(Seedream)、硅基流动(Kolors)、Pollinations(免注册)、自定义 OpenAI 兼容。
各渠道响应格式不同，统一归一化后下载保存到本地。"""
import random
import re
import time
from pathlib import Path
from urllib.parse import quote

import httpx

# 该渠道中文文字渲染是否可靠（豆包 Seedream 可以，免费渠道不建议图内渲染文字）
TEXT_RENDER = {"volcano": True, "siliconflow": False, "pollinations": False, "custom": False, "none": False}


class ImageError(Exception):
    pass


def _ext_from_content_type(ct: str) -> str:
    if "png" in ct:
        return ".png"
    if "webp" in ct:
        return ".webp"
    if "svg" in ct:
        return ".svg"
    return ".jpg"


async def _download(url: str, out_dir: Path, headers: dict | None = None) -> Path:
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        r = await client.get(url, headers=headers or {})
        if r.status_code != 200:
            raise ImageError(f"图片下载失败（{r.status_code}）：{r.text[:200]}")
        path = out_dir / f"soup_{int(time.time())}_{random.randint(1000, 9999)}{_ext_from_content_type(r.headers.get('content-type', ''))}"
        path.write_bytes(r.content)
        return path


async def _gen_volcano(cfg: dict, prompt: str, out_dir: Path) -> Path:
    """火山方舟（豆包 Seedream）：OpenAI images 风格。"""
    base = (cfg.get("base_url") or "https://ark.cn-beijing.volces.com/api/v3").rstrip("/")
    url = base + "/images/generations"
    payload = {"model": cfg.get("model") or "doubao-seedream-4-0-250828",
               "prompt": prompt, "size": cfg.get("size") or "1024x1024",
               "response_format": "url", "watermark": True}
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(url, json=payload,
                              headers={"Authorization": f"Bearer {cfg.get('api_key', '')}"})
        if r.status_code != 200:
            raise ImageError(_friendly(r.status_code, r.text))
        try:
            img_url = r.json()["data"][0]["url"]
        except Exception:
            raise ImageError(f"火山返回格式异常：{r.text[:300]}")
    return await _download(img_url, out_dir)


async def _gen_siliconflow(cfg: dict, prompt: str, out_dir: Path) -> Path:
    base = (cfg.get("base_url") or "https://api.siliconflow.cn/v1").rstrip("/")
    url = base + "/images/generations"
    payload = {"model": cfg.get("model") or "Kwai-Kolors/Kolors", "prompt": prompt,
               "image_size": cfg.get("size") or "1024x1024", "batch_size": 1}
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(url, json=payload,
                              headers={"Authorization": f"Bearer {cfg.get('api_key', '')}"})
        if r.status_code != 200:
            raise ImageError(_friendly(r.status_code, r.text))
        data = r.json()
        img_url = (data.get("images") or data.get("data") or [{}])[0].get("url")
        if not img_url:
            raise ImageError(f"硅基流动返回格式异常：{str(data)[:300]}")
    return await _download(img_url, out_dir)


async def _gen_pollinations(cfg: dict, prompt: str, out_dir: Path) -> Path:
    """完全免费、无需 Key。GET 直接返回图片字节。"""
    base = (cfg.get("base_url") or "https://image.pollinations.ai").rstrip("/")
    w, h = _parse_size(cfg.get("size") or "1024x1024")
    url = f"{base}/prompt/{quote(prompt, safe='')}?width={w}&height={h}&nologo=true&seed={random.randint(1, 10**6)}"
    return await _download(url, out_dir)


async def _gen_custom(cfg: dict, prompt: str, out_dir: Path) -> Path:
    """自定义 OpenAI 兼容 /images/generations，兼容 data[].url 与 images[].url 两种返回。"""
    base = (cfg.get("base_url") or "").rstrip("/")
    if not base:
        raise ImageError("自定义生图未填写 Base URL")
    url = base if base.endswith("/images/generations") else base + "/images/generations"
    if not (cfg.get("model") or "").strip():
        raise ImageError("自定义生图未填写模型名称")
    payload = {"model": cfg["model"].strip(), "prompt": prompt, "size": cfg.get("size") or "1024x1024"}
    async with httpx.AsyncClient(timeout=300) as client:
        r = await client.post(url, json=payload,
                              headers={"Authorization": f"Bearer {cfg.get('api_key', '')}"})
        if r.status_code != 200:
            raise ImageError(_friendly(r.status_code, r.text))
        data = r.json()
        item = (data.get("data") or data.get("images") or [{}])[0]
        if item.get("url"):
            return await _download(item["url"], out_dir)
        if item.get("b64_json"):
            import base64
            path = out_dir / f"soup_{int(time.time())}_{random.randint(1000, 9999)}.png"
            path.write_bytes(base64.b64decode(item["b64_json"]))
            return path
    raise ImageError("自定义生图接口返回中没有图片 url 或 b64_json")


def _friendly(code: int, body: str) -> str:
    b = body[:300]
    if code == 401:
        return f"生图 API Key 无效（401）。请到「设置→生图」检查 Key。平台返回：{b}"
    if code == 403:
        return f"生图接口拒绝访问（403）。常见原因：未开通该模型、未实名认证。平台返回：{b}"
    if code == 429:
        return f"生图触发限流或额度不足（429）。平台返回：{b}"
    return f"生图接口异常（{code}）：{b}"


def _parse_size(s: str) -> tuple[int, int]:
    m = re.match(r"(\d+)\s*[xX×]\s*(\d+)", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else (1024, 1024)


async def generate_image(cfg: dict, prompt: str, out_dir: Path) -> Path:
    provider = cfg.get("provider", "none")
    out_dir.mkdir(parents=True, exist_ok=True)
    if provider == "none":
        raise ImageError("未启用生图渠道")
    if provider == "volcano":
        return await _gen_volcano(cfg, prompt, out_dir)
    if provider == "siliconflow":
        return await _gen_siliconflow(cfg, prompt, out_dir)
    if provider == "pollinations":
        return await _gen_pollinations(cfg, prompt, out_dir)
    return await _gen_custom(cfg, prompt, out_dir)
