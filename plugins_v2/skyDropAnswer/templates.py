# -*- coding: utf-8 -*-
# 天空答题 · 模板管理（加载/保存/去重/学习/验证/匹配 + 模板 API）

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from .models import _KV_COUNT_PREFIX, _PROMPT_LEARN, _TEMPLATES_DIR, _rank, _same_type


def _load_template_namespace(filepath: Path) -> dict:
    """加载单个 .py 模板文件到 namespace dict。

    模板以完整 builtins 执行（非沙箱）：学习出来的脚本需要 import re、
    collections 等标准库能力，这是本插件的设计前提。
    """
    ns = {"__builtins__": __builtins__}
    try:
        exec(filepath.read_text(encoding="utf-8"), ns)
    except Exception:
        return {}
    return ns


def _extract_script_code(filepath: Path) -> str:
    """从模板文件里取出 extract 函数源码（从 def extract 行到文件尾），供前端编辑。"""
    try:
        lines = filepath.read_text(encoding="utf-8").split("\n")
    except Exception:
        return ""
    for i, ln in enumerate(lines):
        if ln.startswith("def extract"):
            return "\n".join(lines[i:]).rstrip() + "\n"
    return ""


def _load_all_templates() -> list[dict]:
    """从 templates/ 目录加载所有 .py 模板"""
    _TEMPLATES_DIR.mkdir(exist_ok=True)
    out = []
    for f in sorted(_TEMPLATES_DIR.glob("*.py")):
        if f.name.startswith("__"):
            continue
        ns = _load_template_namespace(f)
        if "extract" not in ns or "REGEX" not in ns:
            continue
        out.append(
            {
                "id": f.stem,
                "type": ns.get("TYPE", "未知"),
                "regex": ns["REGEX"],
                "status": ns.get("STATUS", "verified"),
                "verify_count": ns.get("VERIFY_COUNT", 0),
                "count": ns.get("COUNT", 0),
                "sample": ns.get("SAMPLE", ""),
                "script_code": _extract_script_code(f),
                "extract": ns["extract"],
            }
        )
    return out


def _build_template_content(tpl: dict) -> str:
    """按模板字典拼出 .py 文件全文（元数据 + extract 脚本）。

    字符串字段一律用 repr 写入，保证含换行/引号/emoji 的内容也能安全往返。
    """
    return (
        f"# {tpl['id']}.py — {tpl['type']}\n"
        f"TYPE = {tpl['type']!r}\n"
        f"REGEX = {tpl['regex']!r}\n"
        f"STATUS = {tpl['status']!r}\n"
        f"VERIFY_COUNT = {tpl['verify_count']}\n"
        f"SAMPLE = {tpl['sample']!r}\n"
        f"\n"
        f"{tpl['script_code']}\n"
    )


def _write_template_file(tpl: dict) -> None:
    """将模板写入 .py 文件"""
    _TEMPLATES_DIR.mkdir(exist_ok=True)
    filepath = _TEMPLATES_DIR / f"{tpl['id']}.py"
    filepath.write_text(_build_template_content(tpl), encoding="utf-8")


def _delete_template_file(tpl_id: str) -> None:
    """删除模板文件"""
    filepath = _TEMPLATES_DIR / f"{tpl_id}.py"
    if filepath.exists():
        filepath.unlink()


def _save_template_count(tpl_id: str, count: int, ctx: object) -> None:
    """保存模板命中次数到 ctx.kv"""
    ctx.kv.set(f"{_KV_COUNT_PREFIX}{tpl_id}", count)


def _load_template_counts(ctx: object) -> dict[str, int]:
    """从 ctx.kv 读取所有模板的命中次数"""
    counts: dict[str, int] = {}
    for key in ctx.kv.keys():
        if key.startswith(_KV_COUNT_PREFIX):
            tpl_id = key[len(_KV_COUNT_PREFIX) :]
            val = ctx.kv.get(key, 0)
            if isinstance(val, (int, float)):
                counts[tpl_id] = int(val)
    return counts


def _cleanup_stale_counts(templates: list[dict], ctx: object) -> None:
    """清理已删除模板的 kv 计数"""
    active_ids = {t["id"] for t in templates}
    for key in ctx.kv.keys():
        if key.startswith(_KV_COUNT_PREFIX):
            tpl_id = key[len(_KV_COUNT_PREFIX) :]
            if tpl_id not in active_ids:
                ctx.kv.delete(key)
                ctx.log.info("清理已删除模板的计数: %s", tpl_id)


def _match_templates(text: str, templates: list[dict]) -> tuple[str | None, dict | None]:
    """遍历模板列表，返回 (extract_fn, tpl_dict) 或 (None, None)"""
    for t in templates:
        regex = t.get("regex", "")
        if not regex:
            continue
        try:
            if re.search(regex, text, re.DOTALL):
                return (t["extract"], t)
        except re.error:
            continue
    return (None, None)


def _update_template_file(tpl: dict, **kwargs: Any) -> None:
    """更新模板的元数据字段并重写文件"""
    for k, v in kwargs.items():
        if k in tpl:
            tpl[k] = v
    filepath = _TEMPLATES_DIR / f"{tpl['id']}.py"
    content = filepath.read_text(encoding="utf-8")
    lines = content.split("\n")
    new_lines = []
    for line in lines:
        changed = False
        for k, v in kwargs.items():
            if line.startswith(f"{k} =") or line.startswith(f"{k}="):
                new_lines.append(f"{k} = {v!r}" if isinstance(v, str) else f"{k} = {v}")
                changed = True
                break
        if not changed:
            new_lines.append(line)
    filepath.write_text("\n".join(new_lines), encoding="utf-8")


def _dedup_templates(templates: list[dict], ctx: object) -> list[dict]:
    """启动时合并同类模板：聚类后每组保留最优者（_rank 最高），命中数累加，
    其余模板删除文件。返回去重后的列表。"""
    groups: list[list[dict]] = []
    for t in templates:
        grp = next((g for g in groups if _same_type(g[0], t)), None)
        if grp is None:
            groups.append([t])
        else:
            grp.append(t)
    kept: list[dict] = []
    for grp in groups:
        if len(grp) == 1:
            kept.append(grp[0])
            continue
        survivor = max(grp, key=_rank)
        survivor["count"] = sum(x.get("count", 0) for x in grp)
        _save_template_count(survivor["id"], survivor["count"], ctx)
        for x in grp:
            if x is not survivor:
                _delete_template_file(x["id"])
                ctx.log.info("启动去重：模板 %s 归并到 %s", x["id"], survivor["id"])
        kept.append(survivor)
    return kept


async def _learn_template(text: str, ans: str, ctx: object, templates: list[dict]) -> None:
    """AI 分析题目 → 生成 .py 模板文件 → 加载到内存"""
    cfg = ctx.config
    if not cfg.get("enable_template_learning", True):
        return
    result = ""
    try:
        existing_lines = [f"- {t.get('id')}: {t.get('type', '')}" for t in templates]
        existing = "\n".join(existing_lines) if existing_lines else "（暂无）"
        prompt = _PROMPT_LEARN.format(text=text[:200], existing=existing)
        result = await ctx.ai.chat(prompt)
        result = result.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(result)

        regex = data.get("regex", "").strip()
        if not regex:
            return

        # 去重：同类题归并到已有模板（filename/type/正则/样例判断），不新建
        hit = next((t for t in templates if _same_type(data, t)), None)
        if hit:
            hit["count"] = hit.get("count", 0) + 1
            hit["sample"] = data.get("sample", text[:50])
            _save_template_count(hit["id"], hit["count"], ctx)
            _update_template_file(hit, sample=hit["sample"])
            ctx.log.info("同类题归并到已有模板 %s（不新建）", hit["id"])
            return

        # 新模板
        filename = data.get("filename", str(int(time.time() * 1000)))
        tpl = {
            "id": filename,
            "type": data.get("type", "未知题型"),
            "regex": regex,
            "script_code": data.get("script_code") or "def extract(text):\n    return " + repr(ans) + "\n",
            "status": "learning",
            "verify_count": 0,
            "count": 1,
            "sample": data.get("sample", text[:50]),
            "extract": None,  # 写入文件后重新加载
        }
        _write_template_file(tpl)
        # 重新加载 extract 函数
        ns = _load_template_namespace(_TEMPLATES_DIR / f"{filename}.py")
        tpl["extract"] = ns.get("extract", lambda t: None)
        templates.append(tpl)
        ctx.log.info("学习新模板: %s | %s | status=learning | 共%d个", tpl["type"], regex[:40], len(templates))
    except Exception as e:
        ctx.log.warning("模板学习失败: %r", e)
        try:
            ctx.log.warning("AI原始响应(前200字): %s", result[:200])
        except Exception:
            pass


async def _verify_template(ai_ans: str, script_ans: str | None, tpl: dict, ctx: object) -> str | None:
    """验证循环：script vs AI → 一致则 verify_count++，3 次达标升 verified"""
    if script_ans and ai_ans and script_ans == ai_ans:
        tpl["verify_count"] = tpl.get("verify_count", 0) + 1
        if tpl["verify_count"] >= 3:
            tpl["status"] = "verified"
            ctx.log.info("模板升级 verified: %s", tpl["id"])
        _update_template_file(tpl, verify_count=tpl["verify_count"], status=tpl["status"])
        return script_ans
    else:
        if tpl.get("verify_count", 0) > 0:
            tpl["verify_count"] = 0
            _update_template_file(tpl, verify_count=0)
        return None


def load_templates(ctx: object) -> list[dict]:
    """启动时加载模板：去重 + 从 kv 恢复命中计数 + 清理过期计数。返回模板列表。"""
    templates = _dedup_templates(_load_all_templates(), ctx)
    ctx.log.info("加载 %d 个模板文件", len(templates))

    # 从 kv 读取模板命中次数，合并到模板字典（优先级高于 .py 文件中的残留 COUNT）
    # 同时清理已删除模板的过期计数
    _cleanup_stale_counts(templates, ctx)
    kv_counts = _load_template_counts(ctx)
    for tpl in templates:
        kv_val = kv_counts.get(tpl["id"])
        if kv_val is not None:
            tpl["count"] = kv_val
    if kv_counts:
        ctx.log.info("从 kv 恢复 %d 个模板的命中次数", len(kv_counts))
    return templates


def register_api(ctx: object, templates: list[dict]) -> None:
    """注册模板管理的后端接口（供 Vue 配置面板调用）。"""

    @ctx.on_api("/api/templates", methods=["GET"])
    async def _get_templates(req: object) -> dict:
        return {"ok": True, "data": [{k: v for k, v in t.items() if k != "extract"} for t in templates]}

    @ctx.on_api("/api/templates/save", methods=["POST"])
    async def _save_template(req: object) -> dict:
        data = req.json or {}
        tid = data.get("id", "")
        tpl = next((t for t in templates if t["id"] == tid), None)
        if tpl is None:
            return {"ok": False, "message": "模板不存在"}
        new_regex = (data.get("regex") or "").strip()
        new_code = data.get("script_code") or ""
        if not new_regex:
            return {"ok": False, "message": "正则不能为空"}
        if "def extract" not in new_code:
            return {"ok": False, "message": "脚本必须定义 extract(text) 函数"}
        # 先校验后落盘：在内存执行确认脚本可用、正则合法，通过才写文件
        candidate = dict(tpl)
        candidate["regex"] = new_regex
        candidate["script_code"] = new_code.rstrip() + "\n"
        ns = {"__builtins__": __builtins__}
        try:
            exec(_build_template_content(candidate), ns)
        except Exception as e:
            return {"ok": False, "message": f"脚本/正则错误：{e}"}
        if "extract" not in ns:
            return {"ok": False, "message": "脚本执行后未生成 extract(text) 函数"}
        try:
            re.compile(new_regex)
        except re.error as e:
            return {"ok": False, "message": f"正则不合法：{e}"}
        # 校验通过：落盘 + 更新内存（立即对后续题目生效）
        tpl["regex"] = new_regex
        tpl["script_code"] = candidate["script_code"]
        tpl["extract"] = ns["extract"]
        _write_template_file(tpl)
        ctx.log.info("模板已手动微调: %s", tid)
        return {"ok": True, "message": "已保存，后续题目立即生效"}

    @ctx.on_api("/api/templates", methods=["DELETE"])
    async def _delete_template(req: object) -> dict:
        data = req.json or {}
        tid = data.get("id", "")
        if not tid:
            return {"ok": False, "message": "缺少 id"}
        _delete_template_file(tid)
        # 从内存列表移除
        for i, t in enumerate(templates):
            if t["id"] == tid:
                templates.pop(i)
                break
        ctx.log.info("删除模板: %s", tid)
        return {"ok": True, "message": "已删除"}

    @ctx.on_api("/api/templates/clear", methods=["POST"])
    async def _clear_templates(req: object) -> dict:
        kept = [t for t in templates if t["id"].startswith("builtin_")]
        removed = [t for t in templates if not t["id"].startswith("builtin_")]
        for t in removed:
            _delete_template_file(t["id"])
        templates.clear()
        templates.extend(kept)
        ctx.log.info("清空 %d 个学习模板", len(removed))
        return {"ok": True, "message": f"已清空，保留 {len(kept)} 个内置模板"}
