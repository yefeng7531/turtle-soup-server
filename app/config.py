"""配置读写与平台预设。所有 Key 只存服务器本地 data/config.json，绝不发给浏览器。"""
import json
import os
import threading
from pathlib import Path

DATA_DIR = Path(os.environ.get("TURTLE_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
CONFIG_PATH = DATA_DIR / "config.json"
OUTPUT_DIR = DATA_DIR / "output"

_lock = threading.Lock()

# 对话平台预设：全部走 OpenAI 兼容 /chat/completions，填 Key 即用
CHAT_PRESETS = {
    "deepseek": {"name": "DeepSeek", "base_url": "https://api.deepseek.com/v1",
                 "models": ["deepseek-chat", "deepseek-reasoner"],
                 "key_url": "https://platform.deepseek.com/api_keys"},
    "siliconflow": {"name": "硅基流动 SiliconFlow", "base_url": "https://api.siliconflow.cn/v1",
                    "models": ["deepseek-ai/DeepSeek-V3", "deepseek-ai/DeepSeek-R1",
                               "Qwen/Qwen2.5-72B-Instruct", "Qwen/Qwen3-32B", "THUDM/GLM-4-9B-0414"],
                    "key_url": "https://cloud.siliconflow.cn/account/ak"},
    "moonshot": {"name": "Kimi (Moonshot)", "base_url": "https://api.moonshot.cn/v1",
                 "models": ["moonshot-v1-32k", "kimi-k2-0905-preview"],
                 "key_url": "https://platform.moonshot.cn/console/api-keys"},
    "zhipu": {"name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
              "models": ["glm-4.5", "glm-4.5-air", "glm-4-flash"],
              "key_url": "https://open.bigmodel.cn/usercenter/apikeys"},
    "dashscope": {"name": "阿里通义 Qwen", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                  "models": ["qwen-max", "qwen-plus", "qwen-turbo"],
                  "key_url": "https://bailian.console.aliyun.com/?apiKey=1"},
    "openrouter": {"name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
                   "models": [], "key_url": "https://openrouter.ai/keys"},
    "ollama": {"name": "Ollama 本地模型", "base_url": "http://127.0.0.1:11434/v1",
               "models": [], "key_url": ""},
    "custom": {"name": "自定义 OpenAI 兼容平台", "base_url": "", "models": [], "key_url": ""},
}

# 生图渠道预设。text_render=True 表示该渠道中文文字渲染可靠，允许在图里写中文标题
IMAGE_PRESETS = {
    "none": {"name": "不生成图片", "base_url": "", "models": [], "text_render": False},
    "volcano": {"name": "豆包 / 火山引擎 Seedream（中文出图最好）",
                "base_url": "https://ark.cn-beijing.volces.com/api/v3",
                "models": ["doubao-seedream-4-0-250828", "doubao-seedream-3-0-t2i-250415"],
                "key_url": "https://console.volcengine.com/ark/region:ark+cn-beijing/apiKey",
                "text_render": True},
    "siliconflow": {"name": "硅基流动 Kolors（免费）",
                    "base_url": "https://api.siliconflow.cn/v1",
                    "models": ["Kwai-Kolors/Kolors"],
                    "key_url": "https://cloud.siliconflow.cn/account/ak",
                    "text_render": False},
    "pollinations": {"name": "Pollinations（完全免费、无需注册）",
                     "base_url": "https://image.pollinations.ai", "models": ["flux"],
                     "key_url": "", "text_render": False},
    "custom": {"name": "自定义 OpenAI 兼容生图接口", "base_url": "", "models": [], "text_render": False},
}

DEFAULT_CONFIG = {
    "access_password": "",
    "host_enabled": True,
    "chat": {"provider": "deepseek", "base_url": "https://api.deepseek.com/v1", "api_key": "", "model": "deepseek-chat", "temperature": 0.8},
    "image": {"provider": "none", "base_url": "", "api_key": "", "model": "", "size": "1024x1024"},
}


def load_config() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k, v in saved.items():
                if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                    cfg[k].update(v)
                else:
                    cfg[k] = v
        except Exception:
            pass  # 配置损坏时回退默认，避免整个服务起不来
    return cfg


def save_config(cfg: dict):
    with _lock:
        CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def sanitized(cfg: dict) -> dict:
    """发给前端的脱敏配置：不回传完整 Key，只回传尾 4 位。"""

    def mask(d: dict) -> dict:
        out = dict(d)
        key = out.get("api_key") or ""
        out["has_key"] = bool(key)
        out["api_key"] = ""
        out["key_tail"] = key[-4:] if len(key) >= 8 else ""
        return out

    return {"access_password_set": bool(cfg.get("access_password")),
            "host_enabled": cfg.get("host_enabled", True),
            "chat": mask(cfg["chat"]), "image": mask(cfg["image"]),
            "chat_presets": CHAT_PRESETS, "image_presets": IMAGE_PRESETS}
