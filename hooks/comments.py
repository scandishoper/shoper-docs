"""Render the local, privacy-filtered Valine archive alongside new Giscus comments."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
import json
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import bleach
import markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markupsafe import Markup
from xml.etree.ElementTree import Element


# The three shortcodes actually used in the export. Unknown codes stay as text.
# Sources: Valine 1.5.1 default expressions and valine.js.org/emoji.html.
EMOJI = {
    "longing": "https://img.t.sinajs.cn/t4/appstyle/expression/ext/normal/c9/2018new_chongjing_org.png",
    "tv_亲亲": "https://i0.hdslb.com/bfs/emote/a8111ad55953ef5e3be3327ef94eb4a39d535d06.png",
    "tv_doge": "https://i0.hdslb.com/bfs/emote/6ea59c827c414b4a2955fe79e0f6fd3dcd515e24.png",
}
SOURCE_TITLES = {
    "/2025/03/02/C++核心编程/": "c++核心",
    "/2025/04/03/创业课章节测试答案参考/": "创业课章节测试答案参考（按旧链接命名）",
    "/2025/08/01/p0/": "旧文 p0（标题待确认）",
}
_by_source: dict[str, list[dict]] = {}


class _EmojiProcessor(InlineProcessor):
    def handleMatch(self, match, data):
        name = match.group(1)
        if name not in EMOJI:
            return None, None, None
        image = Element("img", {
            "src": EMOJI[name], "alt": f":{name}:", "title": name,
            "class": "paper-legacy-emoji", "loading": "lazy", "referrerpolicy": "no-referrer",
        })
        return image, match.start(0), match.end(0)


class _EmojiExtension(Extension):
    def extendMarkdown(self, md):
        # Run below backtick code spans so code examples keep their literal text.
        md.inlinePatterns.register(_EmojiProcessor(r":(longing|tv_亲亲|tv_doge):", md), "legacy_emoji", 175)


def _allowed_attribute(tag: str, name: str, value: str) -> bool:
    if tag == "a":
        if name == "title":
            return True
        return name == "href" and urlsplit(value).scheme.lower() in ("http", "https")
    if tag == "img":
        if name == "src":
            return value in EMOJI.values()
        return name in {"alt", "title", "class", "loading", "referrerpolicy"}
    return False


def render_body(text: str) -> Markup:
    """Keep Markdown and known emoji, but never execute imported HTML or URLs."""
    # Escape raw HTML before Markdown parsing; sanitize generated links as well.
    html = markdown.markdown(escape(text, quote=False), extensions=["nl2br", "fenced_code", _EmojiExtension()])
    cleaned = bleach.clean(
        html,
        tags={"p", "br", "strong", "em", "b", "i", "blockquote", "pre", "code", "ul", "ol", "li", "a", "img", "hr"},
        attributes=_allowed_attribute,
        protocols={"http", "https"},
        strip=True,
    )
    return Markup(cleaned)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Legacy comment timestamp is missing a timezone")
    return parsed


def build_threads(records: list[dict]) -> list[dict]:
    """Restore reply trees, keeping replies to deleted parents visible."""
    nodes = {}
    for record in sorted(records, key=lambda item: (_timestamp(item["created_at"]), item["id"])):
        identifier = record["id"]
        if identifier in nodes:
            raise ValueError(f"Duplicate legacy comment ID: {identifier}")
        published = record.get("published_at") or record["created_at"]
        original = record["original_path"]
        nodes[identifier] = {
            "id": identifier,
            "author": record["author"],
            "created_at": published,
            "date_display": _timestamp(published).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
            "body_html": render_body(record["body"]),
            "reply_to": "",
            "children": [],
            "source_title": SOURCE_TITLES.get(original, unquote(original.rstrip("/").split("/")[-1])),
            "source_url": "https://blog.scandidreams.top" + quote(original, safe="/+()"),
        }
    by_id = {record["id"]: record for record in records}
    roots = []
    for identifier, node in nodes.items():
        record = by_id[identifier]
        parent_id = record.get("parent_id")
        parent = nodes.get(parent_id)
        visited = {identifier}
        ancestor = parent_id
        while ancestor in by_id:
            if ancestor in visited:
                raise ValueError(f"Cyclic legacy reply chain: {identifier}")
            visited.add(ancestor)
            ancestor = by_id[ancestor].get("parent_id")
        if parent and by_id[parent_id]["original_path"] == record["original_path"]:
            node["reply_to"] = parent["author"]
            parent["children"].append(node)
        else:
            if parent_id:
                node["reply_to"] = "原评论已缺失"
            roots.append(node)
    return roots


def on_config(config):
    global _by_source
    _by_source = defaultdict(list)
    archive = Path(config.config_file_path).parent / "data/legacy-comments.json"
    if archive.is_file():
        data = json.loads(archive.read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("Unsupported legacy comment archive format")
        for record in data["comments"]:
            _by_source[record["source"]].append(record)
    return config


def on_page_context(context, *, page, config, nav):
    records = _by_source.get(page.file.src_uri, [])
    context.update(legacy_comments=build_threads(records), legacy_comment_count=len(records))
    return context
