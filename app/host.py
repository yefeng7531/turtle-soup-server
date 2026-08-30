"""AI 主持模式：玩家提问，AI 只回答"是/否/与此无关"，依据生成时的汤底与预判问答判定。"""
from . import db, llm
from .prompts import HOST_GREETING, HOST_SYSTEM


class HostError(Exception):
    pass


def build_pack_from_soup(soup: dict) -> dict:
    d = soup["data"]
    return {"surface": d.get("surface", ""), "base": d.get("base", ""),
            "clues": d.get("clues", []), "hints": d.get("hints", []),
            "qa": d.get("qa", []), "title": d.get("title", "")}


def _system_prompt(pack: dict) -> str:
    return (HOST_SYSTEM
            .replace("{surface}", pack.get("surface", "（无）"))
            .replace("{base}", pack.get("base", "（无）"))
            .replace("{clues}", "\n".join(f"{i + 1}. {c}" for i, c in enumerate(pack.get("clues", []))) or "无")
            .replace("{hints}", "\n".join(f"提示{i + 1}：{h}" for i, h in enumerate(pack.get("hints", []))) or "无")
            .replace("{qa}", _qa_text(pack)))


def _qa_text(pack: dict) -> str:
    rows = [f"问：{item.get('q', '')}　答：{item.get('a', '')}" for item in pack.get("qa", [])]
    return "\n".join(rows) if rows else "（无预判问答，依据汤底自由判定）"


async def chat_reply(session_id: int, pack: dict, user_message: str, cfg: dict):
    """返回流式回复生成器。先落库用户消息，流结束后由调用方落库回复。"""
    db.append_host_message(session_id, "user", user_message)
    history = db.get_host_messages(session_id)[-40:]  # 防止长局撑爆上下文
    messages = [{"role": "system", "content": _system_prompt(pack)}] + \
               [{"role": m["role"], "content": m["content"]} for m in history]
    return llm.chat_stream(cfg["chat"], messages, max_tokens=2000, temperature=0.3)


def greeting() -> str:
    return HOST_GREETING
