"""内容小结文章阅读页（Markdown 渲染为 HTML）。"""

from __future__ import annotations

import html
import re
from typing import Optional


def _inline_md(text: str) -> str:
    s = html.escape(text)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"\*(.+?)\*", r"<em>\1</em>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    return s


def markdown_to_html(md: str) -> str:
    """轻量 Markdown → HTML（覆盖标题、列表、段落）。"""
    lines = (md or "").splitlines()
    out: list[str] = []
    in_ul = False
    in_ol = False

    def close_lists() -> None:
        nonlocal in_ul, in_ol
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            close_lists()
            continue

        if line.startswith("### "):
            close_lists()
            out.append(f"<h3>{_inline_md(line[4:].strip())}</h3>")
        elif line.startswith("## "):
            close_lists()
            out.append(f"<h2>{_inline_md(line[3:].strip())}</h2>")
        elif line.startswith("# "):
            close_lists()
            out.append(f"<h1>{_inline_md(line[2:].strip())}</h1>")
        elif re.match(r"^[-*]\s+", line):
            if not in_ul:
                close_lists()
                out.append("<ul>")
                in_ul = True
            out.append(f"<li>{_inline_md(re.sub(r'^[-*]\s+', '', line))}</li>")
        elif re.match(r"^\d+\.\s+", line):
            if not in_ol:
                close_lists()
                out.append("<ol>")
                in_ol = True
            out.append(f"<li>{_inline_md(re.sub(r'^\d+\.\s+', '', line))}</li>")
        else:
            close_lists()
            out.append(f"<p>{_inline_md(line)}</p>")

    close_lists()
    return "\n".join(out)


def render_article_page(
    video_id: str,
    title: str,
    markdown: str,
    entry_count: int = 0,
    updated: Optional[int] = None,
) -> str:
    body = markdown_to_html(markdown)
    safe_title = html.escape(title or f"视频 {video_id} 内容小结")
    safe_vid = html.escape(video_id)
    meta = f"基于 {entry_count} 条字幕生成" if entry_count else ""
    yt = f"https://www.youtube.com/watch?v={html.escape(video_id, quote=True)}"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{safe_title} · YoutubeSubSync</title>
<style>
  :root {{
    --bg: #0b1220; --card: #111827; --text: #e5e7eb; --muted: #9ca3af;
    --accent: #6366f1; --line: #1f2937;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font-family: Georgia, "Songti SC", "PingFang SC", "Microsoft YaHei", serif;
    line-height: 1.75;
  }}
  .top {{
    border-bottom: 1px solid var(--line); background: rgba(17,24,39,.95);
    padding: 14px 20px; font-family: -apple-system, sans-serif; font-size: 13px;
    display: flex; gap: 12px; align-items: center; flex-wrap: wrap;
  }}
  .top a {{ color: #a5b4fc; text-decoration: none; }}
  .top a:hover {{ text-decoration: underline; }}
  .wrap {{ max-width: 720px; margin: 0 auto; padding: 36px 20px 80px; }}
  article {{
    background: var(--card); border: 1px solid var(--line); border-radius: 16px;
    padding: 36px 32px; box-shadow: 0 20px 50px rgba(0,0,0,.35);
  }}
  .meta {{ color: var(--muted); font-size: 13px; margin-bottom: 24px;
    font-family: -apple-system, sans-serif; }}
  article h1 {{ font-size: 28px; line-height: 1.3; margin: 0 0 20px; }}
  article h2 {{ font-size: 20px; margin: 28px 0 12px; color: #f3f4f6; }}
  article h3 {{ font-size: 17px; margin: 22px 0 10px; color: #d1d5db; }}
  article p {{ margin: 0 0 14px; }}
  article ul, article ol {{ margin: 0 0 16px 1.2em; padding: 0; }}
  article li {{ margin: 6px 0; }}
  article code {{
    background: #0f172a; padding: 2px 6px; border-radius: 4px;
    font-family: ui-monospace, monospace; font-size: .92em;
  }}
</style>
</head>
<body>
  <div class="top">
    <a href="/">← 返回设置</a>
    <a href="{yt}" target="_blank" rel="noopener">在 YouTube 打开</a>
    <span style="color:var(--muted)">{safe_vid}</span>
  </div>
  <div class="wrap">
    <article>
      <div class="meta">{html.escape(meta)}</div>
      {body}
    </article>
  </div>
</body>
</html>"""
