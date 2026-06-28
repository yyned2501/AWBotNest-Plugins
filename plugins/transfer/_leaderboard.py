# =============================================================================
# 多站点转账 - 排行榜渲染（文本默认，出图可选）
#
# 出图三档，自动择优、逐级回退，全程不抛错：
#   1) imgkit + wkhtmltoimage（系统装了才用，HTML 渲染质量最好）
#   2) Pillow/PIL 纯 Python 绘制（无需任何系统二进制；平台 venv 一般自带 PIL）
#   3) 纯文本（保底，永远可用）
#
# 即「平台不额外装依赖」时，只要有 PIL 就能出图，不必再装 wkhtmltoimage。
#
# 不 import pyrogram / core / config。
# =============================================================================

import os
import shutil
import uuid

_MEDALS = ["🥇", "🥈", "🥉"]

# PIL 出图配色（与 HTML 版风格一致）
_BG = (102, 126, 234)          # #667eea 紫蓝背景
_CARD = (255, 255, 255)
_INK = (51, 51, 51)            # #333
_SUB = (102, 102, 102)         # #666
_ACCENT = (102, 126, 234)      # ID 列
_TEAL = (78, 205, 196)         # 次数列 #4ecdc4
_RED = (255, 107, 107)         # 金额列 #ff6b6b
_LINE = (238, 238, 238)        # #eee 分隔线
_MEDAL_RGB = [(255, 196, 0), (176, 184, 196), (205, 127, 50)]  # 金/银/铜


def _mask_uid(uid: int | str) -> str:
    s = str(uid)
    if not s or s == "0":
        return "—"
    if len(s) <= 4:
        return s
    if len(s) > 6:
        return f"{s[:3]}***{s[-2:]}"
    return f"{s[:2]}**{s[-1:]}"


def _fmt_amount(v: float) -> str:
    # 整数不带小数，否则保留 1 位
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}"
    return f"{v:,.1f}"


def render_text(entries: list[dict], site_name: str, bonus_name: str,
                direction: str, owner_name: str = "") -> str:
    """渲染文本排行榜。direction: 'in'=打赏总榜 / 'out'=赏赐总榜。"""
    title_word = "打赏" if direction == "in" else "赏赐"
    head = f"🏆 {site_name} {title_word}总榜 TOP{len(entries)}"
    if owner_name:
        head = f"🏆 {owner_name} · {site_name} {title_word}总榜 TOP{len(entries)}"
    if not entries:
        return f"{head}\n\n暂无数据。"
    lines = [head, ""]
    for e in entries:
        rank = e["rank"]
        medal = _MEDALS[rank - 1] if rank <= 3 else f"{rank:>2}."
        name = e["user_name"]
        name = (name[:10] + "…") if len(name) > 11 else name
        amt = _fmt_amount(e["total"])
        lines.append(f"{medal} {name}  {amt} {bonus_name}（{e['count']}次）")
    return "\n".join(lines)


def render_user_summary(stat: dict, bonus_name: str, direction: str,
                        user_name: str, amount: float) -> str:
    """单笔转账后的个人累计文案（用于 notification）。"""
    title_word = "打赏" if direction == "in" else "赏赐"
    if direction == "in":
        head = (f"👤 {user_name} 大佬，感谢打赏！\n"
                f"💰 本次收到：{_fmt_amount(abs(amount))} {bonus_name}")
    else:
        head = (f"👤 {user_name}\n"
                f"🎁 这是赏赐你的 {_fmt_amount(abs(amount))} {bonus_name}，拿去花！")
    rank_str = f"第 {stat['rank']} 名" if stat.get("rank", -1) > 0 else "—"
    tail = (f"📊 累计{title_word}：{stat['count']} 次，共 "
            f"{_fmt_amount(stat['total'])} {bonus_name}\n"
            f"🏆 {title_word}总榜：{rank_str}")
    return f"{head}\n{tail}"


def _imgkit_available() -> bool:
    """imgkit + wkhtmltoimage 是否可用（最佳画质路径）。"""
    try:
        import imgkit  # noqa: F401
    except Exception:
        return False
    return shutil.which("wkhtmltoimage") is not None


def _pil_available() -> bool:
    """Pillow 是否可用（纯 Python，无需系统二进制）。"""
    try:
        from PIL import Image, ImageDraw, ImageFont  # noqa: F401
    except Exception:
        return False
    return True


def image_available() -> bool:
    """是否具备任意一种出图能力（imgkit 或 PIL）。"""
    return _imgkit_available() or _pil_available()


def render_image(entries: list[dict], site_name: str, bonus_name: str,
                 direction: str, owner_name: str, out_dir) -> str | None:
    """渲染 PNG 排行榜，返回文件路径；不可用/失败返回 None（调用方回退文本）。

    优先 imgkit（HTML 渲染最好看），不可用时退 PIL 纯 Python 绘制。
    """
    if not entries:
        return None
    if _imgkit_available():
        path = _render_image_imgkit(entries, site_name, bonus_name,
                                    direction, owner_name, out_dir)
        if path:
            return path
        # imgkit 标称可用但实际失败 → 继续尝试 PIL
    if _pil_available():
        return _render_image_pil(entries, site_name, bonus_name,
                                 direction, owner_name, out_dir)
    return None


def _render_image_imgkit(entries: list[dict], site_name: str, bonus_name: str,
                         direction: str, owner_name: str, out_dir) -> str | None:
    """imgkit + wkhtmltoimage 路径。失败返回 None。"""
    try:
        import imgkit
        title_word = "打赏" if direction == "in" else "赏赐"
        rows = ""
        for e in entries:
            rank = e["rank"]
            medal = _MEDALS[rank - 1] if rank <= 3 else f"TOP{rank}"
            rows += (
                f"<tr><td class='r'>{medal}</td>"
                f"<td class='i'>{_mask_uid(e['user_id'])}</td>"
                f"<td class='n'>{_html_escape(e['user_name'])}</td>"
                f"<td class='c'>{e['count']}</td>"
                f"<td class='a'>{_fmt_amount(e['total'])}</td></tr>"
            )
        owner = owner_name or site_name
        html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
        body{{background:#667eea;font-family:Arial,'Microsoft YaHei',sans-serif;padding:6px;margin:0}}
        .box{{background:#fff;padding:10px;width:500px;border-radius:6px}}
        .t{{text-align:center;color:#333;font-size:20px;font-weight:bold;margin-bottom:4px}}
        .s{{text-align:center;color:#666;font-size:14px;margin-bottom:10px}}
        table{{width:100%;border-collapse:collapse;font-size:14px}}
        thead{{background:#667eea}} th{{padding:7px 4px;color:#fff;font-size:13px}}
        td{{padding:6px 4px;text-align:center;color:#333;border-bottom:1px solid #eee;font-size:13px}}
        .r{{font-weight:bold}} .i{{color:#667eea}} .n{{font-weight:600}}
        .c{{color:#4ecdc4;font-weight:bold}} .a{{color:#ff6b6b;font-weight:bold}}
        </style></head><body><div class="box">
        <div class="t">🌟 {_html_escape(owner)} 的{title_word}数据终端 🌟</div>
        <div class="s">&gt;&gt;&gt; {site_name} TOP{len(entries)} 排行榜 &lt;&lt;&lt;</div>
        <table><thead><tr><th>⚡排名</th><th>🆔ID</th><th>👤用户</th>
        <th>📊次数</th><th>💰{bonus_name}</th></tr></thead><tbody>{rows}</tbody></table>
        </div></body></html>"""

        out_dir = str(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        uid = uuid.uuid4().hex
        html_path = os.path.join(out_dir, f"_lb_{uid}.html")
        img_path = os.path.join(out_dir, f"_lb_{uid}.png")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        options = {"encoding": "UTF-8", "format": "png", "width": 500, "quiet": ""}
        try:
            imgkit.from_file(html_path, img_path, options=options)
        finally:
            if os.path.exists(html_path):
                os.unlink(html_path)
        return img_path if os.path.exists(img_path) else None
    except Exception:
        return None


# ─── PIL 纯 Python 出图（无需系统二进制） ─────────────────────────────────────
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _load_font(size: int):
    """找一个能显示中文的字体；都没有则退 PIL 内置位图字体（仅 ASCII）。"""
    from PIL import ImageFont
    for path in _FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _text_w(draw, text, font) -> float:
    try:
        return draw.textlength(text, font=font)
    except Exception:
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        return r - l


def _render_image_pil(entries: list[dict], site_name: str, bonus_name: str,
                      direction: str, owner_name: str, out_dir) -> str | None:
    """用 Pillow 绘制排行榜 PNG。失败返回 None。"""
    try:
        from PIL import Image, ImageDraw

        title_word = "打赏" if direction == "in" else "赏赐"
        owner = owner_name or site_name

        # 列：名次 / ID / 用户 / 次数 / 金额
        cols = ["排名", "ID", "用户", "次数", bonus_name]
        col_w = [70, 110, 170, 70, 130]
        W = sum(col_w) + 40                       # 卡片内边距各 20
        row_h = 38
        head_h = 92                               # 标题区
        table_head_h = 40
        n = len(entries)
        card_h = head_h + table_head_h + n * row_h + 16
        pad = 16
        H = card_h + pad * 2

        f_title = _load_font(24)
        f_sub = _load_font(15)
        f_th = _load_font(15)
        f_td = _load_font(15)
        f_medal = _load_font(15)

        img = Image.new("RGB", (W + pad * 2, H), _BG)
        d = ImageDraw.Draw(img)

        # 白卡
        cx0, cy0 = pad, pad
        cx1, cy1 = pad + W, pad + card_h
        d.rounded_rectangle([cx0, cy0, cx1, cy1], radius=12, fill=_CARD)

        # 标题 / 副标题（居中）
        title = f"{owner} 的{title_word}数据终端"
        sub = f">>> {site_name} TOP{n} 排行榜 <<<"
        tw = _text_w(d, title, f_title)
        d.text(((img.width - tw) / 2, cy0 + 18), title, font=f_title, fill=_INK)
        sw = _text_w(d, sub, f_sub)
        d.text(((img.width - sw) / 2, cy0 + 54), sub, font=f_sub, fill=_SUB)

        # 表头背景条
        tx0 = cx0 + 20
        ty0 = cy0 + head_h
        d.rectangle([cx0, ty0, cx1, ty0 + table_head_h], fill=_ACCENT)
        x = tx0
        for i, name in enumerate(cols):
            cw = col_w[i]
            w = _text_w(d, name, f_th)
            d.text((x + (cw - w) / 2, ty0 + (table_head_h - 18) / 2),
                   name, font=f_th, fill=(255, 255, 255))
            x += cw

        # 数据行
        ry = ty0 + table_head_h
        for e in entries:
            rank = e["rank"]
            cells = [
                None,  # 名次单独画（带奖牌圆）
                _mask_uid(e["user_id"]),
                _clip_name(e["user_name"]),
                str(e["count"]),
                _fmt_amount(e["total"]),
            ]
            colors = [_INK, _ACCENT, _INK, _TEAL, _RED]
            x = tx0
            for i, val in enumerate(cells):
                cw = col_w[i]
                cy = ry + (row_h - 18) / 2
                if i == 0:
                    _draw_rank(d, x, ry, cw, row_h, rank, f_medal)
                else:
                    w = _text_w(d, val, f_td)
                    d.text((x + (cw - w) / 2, cy), val, font=f_td, fill=colors[i])
                x += cw
            # 行底分隔线
            d.line([tx0, ry + row_h, cx1 - 20, ry + row_h], fill=_LINE, width=1)
            ry += row_h

        out_dir = str(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        img_path = os.path.join(out_dir, f"_lb_{uuid.uuid4().hex}.png")
        img.save(img_path, "PNG")
        return img_path if os.path.exists(img_path) else None
    except Exception:
        return None


def _draw_rank(d, x, y, cw, row_h, rank: int, font):
    """前三名画金/银/铜圆形 + 名次数字，其余画 'N.'。"""
    cy = y + (row_h - 18) / 2
    if rank <= 3:
        rr = 11
        cxm = x + cw / 2
        cym = y + row_h / 2
        col = _MEDAL_RGB[rank - 1]
        d.ellipse([cxm - rr, cym - rr, cxm + rr, cym + rr], fill=col)
        s = str(rank)
        w = _text_w(d, s, font)
        d.text((cxm - w / 2, cym - 9), s, font=font, fill=(255, 255, 255))
    else:
        s = f"{rank}."
        w = _text_w(d, s, font)
        d.text((x + (cw - w) / 2, cy), s, font=font, fill=_INK)


def _clip_name(name: str) -> str:
    name = str(name or "")
    return (name[:10] + "…") if len(name) > 11 else name


def _html_escape(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))
