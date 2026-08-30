"""生成流水线：把 skill 的工作流程序化。

阶段1 构思汤底（creation-guide 方法论） → 阶段2 反推汤面+配套 →
阶段3 LLM 质检（checklist 六项，fatal 回炉修订，最多 2 轮） → 阶段4 可选生图。
"""
import json
import re
import time
from datetime import datetime

from . import db, imagegen, llm
from .config import OUTPUT_DIR
from .prompts import (JUDGE_SYSTEM, REVISE_USER_PREFIX, STAGE1_SYSTEM, STAGE2_SYSTEM)

MAX_REVISION_ROUNDS = 2


def extract_json(text: str) -> dict:
    """从 LLM 回复中鲁棒地提取 JSON（容忍代码块围栏与前后杂文）。"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("回复中找不到 JSON")
    return json.loads(text[start:end + 1])


def _reqs_str(reqs: dict) -> str:
    return json.dumps(reqs, ensure_ascii=False)


class PipelineError(Exception):
    pass


async def _call_llm_json(cfg: dict, system: str, user: str, *, max_tokens: int, emit, stage: str,
                         stage_key: str = "", idx: int = 0) -> dict:
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    async def on_delta(kind: str, text: str):
        # 实时转发思维链/输出到前端（前端默认折叠+模糊，防剧透）
        await emit({"type": "delta", "index": idx, "stage": stage_key or stage, "kind": kind, "text": text})

    text = await llm.stream_collect(cfg, messages, max_tokens=max_tokens, timeout=600, on_delta=on_delta)
    try:
        return extract_json(text)
    except (ValueError, json.JSONDecodeError) as e:
        await emit({"type": "log", "message": "模型输出无法解析为 JSON，自动重试一次…", "level": "warn"})
        await emit({"type": "delta", "index": idx, "stage": stage_key or stage, "kind": "reset", "text": ""})
        messages.append({"role": "assistant", "content": text[:2000]})
        messages.append({"role": "user", "content": "你上一条输出无法被解析（错误：%s）。请重新输出，且只输出一个合法 JSON 对象，不要任何多余文字、注释或代码块围栏。" % e})
        text2 = await llm.stream_collect(cfg, messages, max_tokens=max_tokens, timeout=600, on_delta=on_delta)
        try:
            return extract_json(text2)
        except (ValueError, json.JSONDecodeError) as e2:
            raise PipelineError(f"{stage}阶段：模型两次输出都无法解析为 JSON。请换一个对话模型（如 deepseek-chat）再试。") from e2


async def _generate_one(reqs: dict, cfg: dict, idx: int, total: int, emit, past_titles: list[str]) -> dict:
    """生成单篇：汤底 → 汤面配套 → 质检回炉 →（可选生图在外层做）。"""
    use = reqs.get("use", "主持")
    reqs_i = dict(reqs)
    if idx > 0:
        reqs_i["多篇区分要求"] = f"这是第 {idx + 1}/{total} 篇。已生成：《{'》《'.join(past_titles) or '（无）'}》，本篇请更换主题素材或调整难度档次，避免套路重复。"

    # 阶段 1：汤底
    await emit({"type": "stage", "stage": "base", "index": idx, "message": "构思汤底（先汤底后汤面）…"})
    t0 = time.time()
    base1 = await _call_llm_json(cfg["chat"], STAGE1_SYSTEM.replace("{reqs}", _reqs_str(reqs_i)),
                                 "请开始构思汤底。", max_tokens=8000, emit=emit, stage="汤底构思",
                                 stage_key="base", idx=idx)
    await emit({"type": "log", "message": f"汤底完成：《{base1.get('title', '未命名》')}》（用时 {time.time() - t0:.0f}s）"})

    # 阶段 2：汤面 + 配套
    await emit({"type": "stage", "stage": "surface", "index": idx, "message": "反推汤面、编写线索与问答…"})
    t0 = time.time()
    user2 = f"【已定稿汤底】\n{json.dumps(base1, ensure_ascii=False)}\n\n请反推汤面并编写全套配套。"
    stage2 = await _call_llm_json(cfg["chat"], STAGE2_SYSTEM.replace("{base_json}", json.dumps(base1, ensure_ascii=False))
                                  .replace("{reqs}", _reqs_str(reqs_i)), user2, max_tokens=10000, emit=emit, stage="汤面配套",
                                  stage_key="surface", idx=idx)
    await emit({"type": "log", "message": f"汤面与配套完成（用时 {time.time() - t0:.0f}s）"})

    # 阶段 3：质检回炉
    rounds = 0
    judge = {"pass": True, "fatal": [], "warnings": [], "multi_solutions": []}
    while True:
        await emit({"type": "stage", "stage": "judge", "index": idx,
                    "message": f"质检中（第 {rounds + 1} 次审查）…"})
        material = json.dumps({"汤底": base1, "汤面与配套": stage2, "需求": reqs_i}, ensure_ascii=False)
        try:
            judge = await _call_llm_json(cfg["chat"], JUDGE_SYSTEM.replace("{material}", material),
                                         "请逐项审查并输出 JSON。", max_tokens=8000, emit=emit, stage="质检",
                                         stage_key="judge", idx=idx)
        except PipelineError:
            judge = {"pass": True, "fatal": [], "warnings": ["质检环节模型输出异常，已跳过（不影响谜题本身）。"],
                     "multi_solutions": []}
        if judge.get("pass", True) or rounds >= MAX_REVISION_ROUNDS:
            break
        rounds += 1
        await emit({"type": "log",
                    "message": f"质检未通过（{len(judge.get('fatal', []))} 处硬伤），第 {rounds}/{MAX_REVISION_ROUNDS} 次回炉修订…",
                    "level": "warn"})
        await emit({"type": "stage", "stage": "revise", "index": idx, "message": "按质检意见修订…"})
        rev_user = (REVISE_USER_PREFIX
                    .replace("{issues}", "\n".join(f"- {x}" for x in judge.get("fatal", [])) or "无")
                    .replace("{multi_solutions}", "\n".join(f"- {x}" for x in judge.get("multi_solutions", [])) or "无")
                    .replace("{prev_json}", json.dumps(stage2, ensure_ascii=False)[:6000]))
        try:
            stage2 = await _call_llm_json(cfg["chat"], STAGE2_SYSTEM.replace("{base_json}", json.dumps(base1, ensure_ascii=False))
                                          .replace("{reqs}", _reqs_str(reqs_i)), rev_user, max_tokens=10000,
                                          emit=emit, stage="修订", stage_key="revise", idx=idx)
        except PipelineError:
            rounds -= 1  # 修订失败则保留上一版
            break

    pack = {
        "title": stage2.get("title") or base1.get("title") or f"无题之汤",
        "surface": stage2.get("surface", ""),
        "base": base1.get("base", ""),
        "key_new_info": base1.get("key_new_info", ""),
        "clues": stage2.get("clues", []),
        "hints": stage2.get("hints", []),
        "qa": stage2.get("qa", []),
        "tips": stage2.get("tips", ""),
        "hook_titles": stage2.get("hook_titles", []) if use == "文案" else [],
        "badges": {"主题": reqs.get("theme", "悬疑"), "类型": reqs.get("genre", "本格"),
                   "口味": reqs.get("taste", "清汤"), "难度": reqs.get("difficulty", "中等"), "用途": use},
        "meta": {"judge_pass": bool(judge.get("pass", True)), "judge_rounds": rounds,
                 "judge_warnings": judge.get("warnings", []),
                 "difficulty_note": base1.get("difficulty_note", ""),
                 "misdirection": base1.get("misdirection", []), "rule": base1.get("rule", ""),
                 "model": cfg["chat"].get("model") or cfg["chat"].get("provider", ""),
                 "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")},
    }
    return pack


def build_image_prompt(pack: dict, image_cfg: dict) -> str:
    """生图提示词只从【汤面】取材（汤面本身就是公开信息），从根上保证图片不泄底。"""
    preset_text_render = imagegen.TEXT_RENDER.get(image_cfg.get("provider"), False)
    style = ("暗调悬疑插画，电影感构图，克制的光影，神秘氛围，笔触细腻，无血腥、无恐怖特写，画面含蓄留白")
    prompt = f"为下面这段谜题场景画一幅插画（只画场景气氛，不要画出答案）：{pack['surface']}。风格：{style}。画面中不要出现任何解释性文字。"
    if preset_text_render and pack.get("title"):
        prompt += f" 在画面下方以优雅清晰的中文衬线字体渲染标题「{pack['title']}」，字必须准确无错字。"
    return prompt


async def run_generation(reqs: dict, cfg: dict, emit) -> list[int]:
    """完整生成 count 篇，落库并返回 soup id 列表。emit: async fn(event_dict)。"""
    count = max(1, min(int(reqs.get("count", 1)), 5))
    with_image = bool(reqs.get("with_image")) and cfg["image"].get("provider", "none") != "none"
    ids: list[int] = []
    past: list[str] = []
    for idx in range(count):
        await emit({"type": "progress", "index": idx, "total": count, "message": f"开始生成第 {idx + 1}/{count} 篇"})
        pack = await _generate_one(reqs, cfg, idx, count, emit, past)
        past.append(pack["title"])

        image_path = None
        if with_image:
            try:
                await emit({"type": "stage", "stage": "image", "index": idx, "message": "生成汤面插图（不泄底）…"})
                image_path = str(await imagegen.generate_image(cfg["image"], build_image_prompt(pack, cfg["image"]),
                                                               OUTPUT_DIR))
                await emit({"type": "log", "message": "插图已生成。"})
            except Exception as e:
                await emit({"type": "log", "message": f"插图生成失败（不影响谜题）：{e}", "level": "warn"})

        soup_id = db.save_soup(reqs, pack, image_path)
        ids.append(soup_id)
        await emit({"type": "soup", "index": idx, "id": soup_id, "data": pack, "image": image_path})
    await emit({"type": "done", "ids": ids,
                "message": f"全部完成：{len(ids)} 篇已保存到历史记录。"})
    return ids
