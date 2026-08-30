"""海龟汤 AI 工坊 — FastAPI 主入口。

本地试运行：  python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
服务器部署：  docker compose up -d（见 README.md）
"""
import asyncio
import json
import secrets
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db, host, imagegen, llm, pipeline
from .config import OUTPUT_DIR, load_config, save_config, sanitized

WEB_DIR = Path(__file__).resolve().parent / "web"

# 简单口令会话：token 存内存，重启后需重新登录（Key 本就在服务器，无泄露风险）
_TOKENS: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = load_config()
    if not cfg.get("access_password"):
        print("\n⚠️  当前未设置访问口令。本地使用没问题；若部署到公网服务器，请先到「设置」页设置口令！\n")
    import os
    if not os.environ.get("TURTLE_NO_BROWSER"):
        # 本地试运行时自动打开浏览器；服务器上没有浏览器时打开失败会被静默忽略
        asyncio.get_running_loop().call_later(1.2, lambda: webbrowser.open("http://127.0.0.1:8000"))
    yield


app = FastAPI(title="海龟汤 AI 工坊", lifespan=lifespan)


def _auth(request: Request):
    cfg = load_config()
    if cfg.get("access_password") and request.headers.get("X-Auth-Token") not in _TOKENS:
        raise HTTPException(401, "需要登录")


def _err(e: Exception) -> HTTPException:
    return HTTPException(502, str(e) if isinstance(e, (llm.LLMError, pipeline.PipelineError, imagegen.ImageError)) else f"内部错误：{e}")


async def _json_body(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        raise HTTPException(400, "请求体不是合法的 UTF-8 JSON")


# ---------- 状态 / 登录 / 设置 ----------

@app.get("/api/state")
def state():
    cfg = load_config()
    return {"auth_required": bool(cfg.get("access_password")),
            "host_enabled": cfg.get("host_enabled", True)}


@app.post("/api/login")
async def login(request: Request):
    body = await _json_body(request)
    cfg = load_config()
    if not cfg.get("access_password"):
        token = secrets.token_hex(16)
        _TOKENS.add(token)
        return {"token": token, "no_password": True}
    if body.get("password") == cfg["access_password"]:
        token = secrets.token_hex(16)
        _TOKENS.add(token)
        return {"token": token}
    raise HTTPException(403, "口令不正确")


@app.get("/api/settings")
def get_settings(request: Request):
    _auth(request)
    return sanitized(load_config())


@app.post("/api/settings")
async def set_settings(request: Request):
    _auth(request)
    body = await _json_body(request)
    cfg = load_config()
    for section in ("chat", "image"):
        if section in body and isinstance(body[section], dict):
            for k, v in body[section].items():
                if k == "api_key" and not v:  # 前端留空 = 保持原 Key
                    continue
                cfg[section][k] = v
    if "host_enabled" in body:
        cfg["host_enabled"] = bool(body["host_enabled"])
    if body.get("new_password"):
        cfg["access_password"] = str(body["new_password"])
    elif body.get("clear_password"):
        cfg["access_password"] = ""
    save_config(cfg)
    return {"ok": True, **sanitized(cfg)}


# ---------- 连接测试 / 模型列表 ----------

@app.post("/api/models")
async def list_models(request: Request):
    """拉取平台模型列表。表单里刚填的 URL/Key 优先（不必先保存），否则用已保存配置。"""
    _auth(request)
    body = await _json_body(request)
    section = body.get("section") if body.get("section") in ("chat", "image") else "chat"
    cfg = dict(load_config()[section])
    if body.get("base_url"):
        cfg["base_url"] = str(body["base_url"]).strip()
    if body.get("api_key"):
        cfg["api_key"] = str(body["api_key"]).strip()
    try:
        models = await llm.list_models(cfg)
        return {"ok": True, "models": models}
    except llm.LLMError as e:
        return {"ok": False, "message": str(e), "models": []}


@app.post("/api/test/chat")
async def test_chat(request: Request):
    _auth(request)
    cfg = load_config()["chat"]
    try:
        secs = await llm.ping(cfg)
        return {"ok": True, "seconds": secs, "message": f"连接成功（{secs}s）"}
    except llm.LLMError as e:
        return {"ok": False, "message": str(e)}


@app.post("/api/test/image")
async def test_image(request: Request):
    _auth(request)
    cfg = load_config()["image"]
    if cfg["provider"] in ("none",):
        return {"ok": False, "message": "请先选择生图渠道"}
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = await imagegen.generate_image(cfg, "a small test image of a turtle, minimal, dark background", OUTPUT_DIR)
        return {"ok": True, "seconds": 0, "message": f"生图成功，测试图已保存：{path.name}"}
    except imagegen.ImageError as e:
        return {"ok": False, "message": str(e)}


# ---------- 生成（SSE 流式进度） ----------

@app.post("/api/generate")
async def generate(request: Request):
    _auth(request)
    reqs = await _json_body(request)
    chat_cfg = load_config()["chat"]
    if chat_cfg["provider"] != "ollama" and not chat_cfg.get("api_key"):
        raise HTTPException(400, "请先到「设置」选择平台并填写 API Key（本地 Ollama 模型无需 Key）")
    if not chat_cfg.get("model"):
        raise HTTPException(400, "请先到「设置」填写模型名称——可点「获取模型列表」按钮自动拉取后点选")

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: dict):
            await queue.put(event)

        async def worker():
            try:
                await pipeline.run_generation(reqs, load_config(), emit)
            except asyncio.CancelledError:
                await queue.put({"type": "error", "message": "已取消"})
            except (pipeline.PipelineError, llm.LLMError, imagegen.ImageError) as e:
                await queue.put({"type": "error", "message": str(e)})
            except Exception as e:  # noqa: BLE001
                await queue.put({"type": "error", "message": f"生成失败：{e}"})
            finally:
                await queue.put(None)

        task = asyncio.create_task(worker())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
        finally:
            task.cancel()

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------- 历史记录 ----------

@app.get("/api/soups")
def list_soups(request: Request):
    _auth(request)
    return db.list_soups()


@app.get("/api/soups/{soup_id}")
def get_soup(soup_id: int, request: Request):
    _auth(request)
    soup = db.get_soup(soup_id)
    if not soup:
        raise HTTPException(404, "记录不存在")
    return soup


@app.delete("/api/soups/{soup_id}")
def delete_soup(soup_id: int, request: Request):
    _auth(request)
    db.delete_soup(soup_id)
    return {"ok": True}


@app.get("/api/soups/{soup_id}/image")
def soup_image(soup_id: int):
    soup = db.get_soup(soup_id)
    if not soup or not soup["image_path"]:
        raise HTTPException(404, "无插图")
    p = OUTPUT_DIR / Path(soup["image_path"]).name
    return FileResponse(p)


# ---------- 导出 Markdown ----------

def render_md(soup: dict) -> str:
    d, s = soup["data"], soup["settings"]
    badges = f"> 主题：{s.get('theme', '悬疑')} ｜ 类型：{s.get('genre', '本格')} ｜ 口味：{s.get('taste', '清汤')} ｜ 难度：{s.get('difficulty', '中等')} ｜ 用途：{s.get('use', '主持')}"
    use = s.get("use", "主持")
    lines = [f"# 🐢 海龟汤：《{d.get('title', '无题')}》", "", badges, ""]
    if d.get("hook_titles"):
        lines += ["## 备选标题", ""] + [f"{i + 1}. {t}" for i, t in enumerate(d["hook_titles"])] + [""]
    lines += [f"## 🥣 汤面（开场念给玩家）", "", d.get("surface", ""), "",
              "## 🍲 汤底（主持人持有，通关后公布）", "", d.get("base", ""), "",
              "## 🔑 关键线索点", ""]
    lines += [f"{i + 1}. {c}" for i, c in enumerate(d.get("clues", []))]
    hints = d.get("hints", [])
    if hints:
        lines += ["", "## 💡 递进提示（逐级释放）", ""]
        labels = ["提示 1（方向）", "提示 2（缩小范围）", "提示 3（临门一脚）"]
        lines += [f"- {labels[i] if i < 3 else '提示 ' + str(i + 1)}：{h}" for i, h in enumerate(hints)]
    if d.get("qa"):
        lines += ["", "## ❓ 预判问答（口径：是 / 否 / 与此无关）", "", "| 玩家可能的问题 | 回答 |", "| --- | --- |"]
        lines += [f"| {q.get('q', '')} | {q.get('a', '')} |" for q in d["qa"]]
    if d.get("tips"):
        lines += ["", "## 🎙️ 主持贴士", ""] + [f"- {t.strip()}" for t in d["tips"].split("；") if t.strip()]
    meta = d.get("meta", {})
    lines += ["", "---", f"由海龟汤 AI 工坊生成（{meta.get('created_at', '')}，模型 {meta.get('model', '')}，质检{'通过' if meta.get('judge_pass') else '未通过'}）"]
    return "\n".join(lines)


@app.get("/api/soups/{soup_id}/export")
def export_soup(soup_id: int):
    soup = db.get_soup(soup_id)
    if not soup:
        raise HTTPException(404, "记录不存在")
    title = (soup["data"].get("title") or f"海龟汤{soup_id}").replace("/", "_")
    encoded = quote(title + ".md")
    return FileResponse(_tmp_export(soup), media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"})


def _tmp_export(soup: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUTPUT_DIR / f"export_{soup['id']}.md"
    p.write_text(render_md(soup), encoding="utf-8")
    return p


# ---------- AI 主持 ----------

@app.post("/api/host/start")
async def host_start(request: Request):
    _auth(request)
    cfg = load_config()
    if not cfg.get("host_enabled"):
        raise HTTPException(400, "AI 主持模式已在设置中关闭")
    body = await _json_body(request)
    pack = None
    soup_id = body.get("soup_id")
    if soup_id:
        soup = db.get_soup(int(soup_id))
        if not soup:
            raise HTTPException(404, "记录不存在")
        pack = host.build_pack_from_soup(soup)
    elif body.get("surface") and body.get("base"):  # 手动粘贴模式
        pack = {"surface": body["surface"], "base": body["base"], "clues": body.get("clues", []),
                "hints": body.get("hints", []), "qa": body.get("qa", []), "title": body.get("title", "自定汤")}
    else:
        raise HTTPException(400, "请选择历史汤品，或粘贴汤面+汤底")
    session_id = db.create_host_session(soup_id)
    db.append_host_message(session_id, "assistant", host.greeting())
    return {"session_id": session_id, "greeting": host.greeting(),
            "surface": pack.get("surface", "")}


@app.post("/api/host/{session_id}/chat")
async def host_chat(session_id: int, request: Request):
    _auth(request)
    body = await _json_body(request)
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "消息为空")
    soup_id = body.get("soup_id")
    manual = body.get("pack")
    if soup_id:
        soup = db.get_soup(int(soup_id))
        pack = host.build_pack_from_soup(soup) if soup else None
    elif manual:
        pack = {"surface": manual.get("surface", ""), "base": manual.get("base", ""),
                "clues": manual.get("clues", []), "hints": manual.get("hints", []),
                "qa": manual.get("qa", []), "title": manual.get("title", "")}
    else:
        raise HTTPException(400, "缺少谜题上下文")
    if pack is None:
        raise HTTPException(404, "记录不存在")
    cfg = load_config()

    async def event_stream():
        full = []

        async def gen():
            stream = await host.chat_reply(session_id, pack, message, cfg)
            try:
                async for piece in stream:
                    full.append(piece)
                    yield f"data: {json.dumps({'type': 'chunk', 'text': piece}, ensure_ascii=False)}\n\n"
            except llm.LLMError as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        try:
            async for chunk in gen():
                yield chunk
        finally:
            if full:
                db.append_host_message(session_id, "assistant", "".join(full))
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


# ---------- 静态资源（必须在 API 路由之后挂载） ----------

app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR), check_dir=False), name="output")
app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
