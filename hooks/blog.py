"""Build the blog's navigation and reading indexes directly from Markdown files.

Only the six content directories below are editorial categories. A new Markdown
file anywhere beneath one of them is a post; an ``index.md`` is a landing page.
The source path remains the URL, so existing links and URL-based comments survive.
No generated Markdown is written back into ``docs``.
"""

from __future__ import annotations

from collections import OrderedDict
from datetime import date, datetime
import math
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any

from mkdocs.plugins import event_priority
from mkdocs.structure.files import File, Files, InclusionLevel
from mkdocs.utils.meta import get_data


TOPICS = (
    ("algorithms", "算法与题解", "从基础算法到竞赛题解，记录思路、推导与实现。"),
    ("cs", "CS 自学", "沿着课程和书籍，慢慢建立对计算机的理解。"),
    ("technology", "技术实践", "工具、开发与折腾，把学到的东西用起来。"),
    ("life", "随笔与看法", "记录生活中的片段，也留下还在生长的想法。"),
)

CATEGORIES = (
    ("algo", "算法笔记", "algorithms"),
    ("solutions", "题解", "algorithms"),
    ("csdiy", "CS 自学", "cs"),
    ("technology", "技术实践", "technology"),
    ("views", "看法", "life"),
    ("blog", "生活随笔", "life"),
)

# A one-time migration of the old hand-maintained navigation. This never needs
# extending: new posts can declare `series`/`order`, or live in a series folder.
LEGACY_SERIES = {
    "algo": {
        "基础算法": ("p2", "p1", "p5", "p16", "p11", "p9", "p14", "p6"),
        "动态规划": ("p13",),
        "数据结构": ("p12", "p4", "p8", "p3", "p56", "p61"),
        "数论": ("p10", "p15", "p57", "p58", "p59"),
        "图论": ("p7",),
    },
    "csdiy": {
        "CSAPP": ("p34", "p55", "p66"),
        "CS106L": ("p54", "p60"),
        "CMU 15-445": ("p62",),
    },
    "blog": {
        "学期与杂谈": ("p28", "p30", "p31", "p33", "p29", "p32", "p65"),
        "周记": ("p18", "p21", "p22", "p23", "p24", "p25", "p26", "p27", "p19", "p20"),
    },
}

_LEGACY = {
    f"{category}/{stem}.md": (series, position)
    for category, groups in LEGACY_SERIES.items()
    for series, stems in groups.items()
    for position, stem in enumerate(stems, 1)
}

# Replaced on every on_files call, including live-reload builds after deletion.
_posts: list[dict[str, Any]] = []
_topics: list[dict[str, Any]] = []
_categories: list[dict[str, Any]] = []
_archives: list[dict[str, Any]] = []
_post_by_source: dict[str, dict[str, Any]] = {}
_landing_by_source: dict[str, dict[str, Any]] = {}


def parse_date(value: Any) -> date | None:
    """Accept YAML dates, datetimes, dotted dates, and non-zero-padded dates."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    value = value.strip()
    match = re.fullmatch(r"(\d{4})[.-](\d{1,2})[.-](\d{1,2})", value)
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _is_draft(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _first_heading(markdown: str) -> str | None:
    """Find a real ATX H1, ignoring fenced examples and HTML comments."""
    markdown = re.sub(r"<!--.*?-->", "", markdown, flags=re.S)
    fence = None
    fence_size = 0
    for line in markdown.splitlines():
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if fence is None:
                fence, fence_size = run[0], len(run)
            elif run[0] == fence and len(run) >= fence_size:
                fence = None
            continue
        if fence is not None:
            continue
        heading = re.match(r"^ {0,3}#[ \t]+(.+?)\s*$", line)
        if heading:
            title = re.sub(r"\s+#+\s*$", "", heading.group(1))
            title = re.sub(r"\s*\{[^{}]*\}\s*$", "", title)
            title = re.sub(r"!?\[([^]]+)\]\([^)]*\)", r"\1", title)
            return title.strip("`*_ ") or None
    return None


def _git_creation_date(file: File, docs_dir: Path) -> date | None:
    """Follow renames to the oldest commit; untracked/staged files have no log."""
    # A WSL checkout accessed through Windows can have a different owner. Trust
    # only this checkout for this command, without changing global Git settings.
    repository = next((path for path in (docs_dir, *docs_dir.parents) if (path / ".git").exists()), None)
    if repository is None:
        return None
    try:
        result = subprocess.run(
            [
                "git", "-c", f"safe.directory={repository.as_posix()}",
                "-C", str(docs_dir), "log", "--follow", "--format=%aI",
                "--", file.src_uri,
            ],
            check=False, capture_output=True, text=True, encoding="utf-8", timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    dates = [parse_date(line) for line in result.stdout.splitlines()]
    return next((value for value in reversed(dates) if value is not None), None)


def _post_date(metadata: dict, file: File, docs_dir: Path) -> date:
    explicit = parse_date(metadata.get("date"))
    if explicit is not None:
        return explicit
    historical = _git_creation_date(file, docs_dir)
    if historical is not None:
        return historical
    # This is primarily for new, untracked files. CI must fetch full Git history
    # so previously published undated posts keep their original publication day.
    return datetime.fromtimestamp(Path(file.abs_src_path).stat().st_mtime).date()


def _order(value: Any) -> int | float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return int(number) if number.is_integer() else number


def _series_info(metadata: dict, source: str) -> tuple[str, int | float | None]:
    old_series, old_order = _LEGACY.get(source, ("", None))
    path = PurePosixPath(source)
    folder_series = path.parent.name if len(path.parts) > 2 else ""
    series = str(metadata.get("series") or "").strip() if "series" in metadata else old_series or folder_series
    order = _order(metadata.get("order")) if "order" in metadata else (old_order if series == old_series else None)
    return series, order


def _series_sort(post: dict) -> tuple:
    return (post["order"] if post["order"] is not None else math.inf, post["date"], post["source"])


def _groups(posts: list[dict]) -> list[dict]:
    groups: OrderedDict[str, list[dict]] = OrderedDict()
    for post in posts:
        groups.setdefault(post["series"] or "其他文章", []).append(post)
    return [
        {"title": name, "posts": sorted(items, key=_series_sort) if name != "其他文章" else items}
        for name, items in groups.items()
    ]


def _generated_page(files: Files, config, source: str, title: str, template: str) -> File:
    existing = files.get_file_from_path(source)
    if existing is not None:
        return existing
    file = File.generated(
        config, source,
        content=f"---\ntitle: {title}\ntemplate: {template}\nsearch:\n  exclude: true\n---\n",
    )
    files.append(file)
    return file


@event_priority(100)
def on_files(files: Files, *, config) -> Files:
    """Discover posts, remove drafts, and build all derived navigation data."""
    global _posts, _topics, _categories, _archives, _post_by_source, _landing_by_source
    _posts, _topics, _categories, _archives = [], [], [], []
    _post_by_source, _landing_by_source = {}, {}
    docs_dir = Path(config["docs_dir"])
    category_definitions = {key: (title, topic_id) for key, title, topic_id in CATEGORIES}
    topic_definitions = {key: (title, description) for key, title, description in TOPICS}
    sources: list[tuple[File, str, dict]] = []

    for file in list(files.documentation_pages()):
        markdown, metadata = get_data(file.content_string)
        if _is_draft(metadata.get("draft")):
            files.remove(file)
            continue
        sources.append((file, markdown, metadata))

    _generated_page(files, config, "topics.md", "专题", "topics.html")
    _generated_page(files, config, "archive.md", "归档", "archive.html")
    topic_files = {
        key: _generated_page(files, config, f"topics/{key}.md", title, "topic.html")
        for key, title, _ in TOPICS
    }
    category_files = {
        key: _generated_page(files, config, f"{key}/index.md", title, "topic.html")
        for key, title, _ in CATEGORIES
    }

    for file, markdown, metadata in sources:
        path = PurePosixPath(file.src_uri)
        category_id = path.parts[0]
        if category_id not in category_definitions or path.name.lower() == "index.md":
            continue
        category_title, topic_id = category_definitions[category_id]
        topic_title, _ = topic_definitions[topic_id]
        published = _post_date(metadata, file, docs_dir)
        series, order = _series_info(metadata, file.src_uri)
        title = str(metadata.get("title") or "").strip() or _first_heading(markdown) or path.stem
        text = re.sub(r"```.*?```|~~~.*?~~~", "", markdown, flags=re.S)
        reading_minutes = max(1, math.ceil(len(re.findall(r"[\u3400-\u9fff]", text)) / 400 + len(re.findall(r"\b[A-Za-z]+\b", text)) / 200))
        post = {
            "title": title,
            "url": file.url,
            "source": file.src_uri,
            "date": published.isoformat(),
            "date_display": f"{published.year}年{published.month}月{published.day}日",
            "date_short": published.strftime("%m.%d"),
            "year": published.year,
            "category": category_title,
            "category_id": category_id,
            "category_url": category_files[category_id].url,
            "topic": topic_title,
            "topic_id": topic_id,
            "topic_url": topic_files[topic_id].url,
            "summary": str(metadata.get("summary") or metadata.get("description") or "").strip(),
            "series": series,
            "order": order,
            "reading_minutes": reading_minutes,
        }
        _posts.append(post)

    # Stable alphabetical/source tie-breakers make same-day builds reproducible.
    _posts.sort(key=lambda post: (post["title"], post["source"]))
    _posts.sort(key=lambda post: post["date"], reverse=True)
    _post_by_source = {post["source"]: post for post in _posts}

    for key, title, topic_id in CATEGORIES:
        posts = [post for post in _posts if post["category_id"] == key]
        category = {
            "id": key, "title": title, "description": topic_definitions[topic_id][1],
            "url": category_files[key].url, "posts": posts, "groups": _groups(posts),
            "count": len(posts), "topic_id": topic_id,
        }
        _categories.append(category)
        _landing_by_source[f"{key}/index.md"] = category

    for key, title, description in TOPICS:
        posts = [post for post in _posts if post["topic_id"] == key]
        topic = {
            "id": key, "title": title, "description": description,
            "url": topic_files[key].url, "posts": posts, "groups": _groups(posts),
            "count": len(posts),
            "categories": [category for category in _categories if category["topic_id"] == key],
        }
        _topics.append(topic)
        _landing_by_source[f"topics/{key}.md"] = topic

    # A nested folder's optional index is also an automatic landing page.
    for file, _, metadata in sources:
        path = PurePosixPath(file.src_uri)
        if len(path.parts) <= 2 or path.parts[0] not in category_definitions or path.name.lower() != "index.md":
            continue
        prefix = str(path.parent) + "/"
        posts = [post for post in _posts if post["source"].startswith(prefix)]
        _landing_by_source[file.src_uri] = {
            "id": str(path.parent), "title": str(metadata.get("title") or path.parent.name),
            "description": str(metadata.get("description") or ""),
            "url": file.url, "posts": posts, "groups": _groups(posts), "count": len(posts),
        }

    for year in sorted({post["year"] for post in _posts}, reverse=True):
        _archives.append({"year": year, "posts": [post for post in _posts if post["year"] == year]})

    # Four top-level destinations; descendants still get proper MkDocs Pages,
    # breadcrumbs and URL resolution even though the front end has no sidebar.
    topic_nav = [{"专题": "topics.md"}]
    for topic in _topics:
        children = [{topic["title"]: f"topics/{topic['id']}.md"}]
        for category in topic["categories"]:
            category_children = [{category["title"]: f"{category['id']}/index.md"}]
            category_children.extend({post["title"]: post["source"]} for post in category["posts"])
            children.append({category["title"]: category_children})
        topic_nav.append({topic["title"]: children})
    config["nav"] = [{"文章": "index.md"}, {"专题": topic_nav}, {"归档": "archive.md"}]
    if files.get_file_from_path("about.md") is not None:
        config["nav"].append({"关于": "about.md"})

    managed = set(_post_by_source) | {"index.md", "about.md", "archive.md", "topics.md"}
    managed.update(f"{key}/index.md" for key, _, _ in CATEGORIES)
    managed.update(f"topics/{key}.md" for key, _, _ in TOPICS)
    for file in files.documentation_pages():
        if file.src_uri not in managed:
            file.inclusion = InclusionLevel.NOT_IN_NAV
    return files


@event_priority(100)
def on_page_markdown(markdown: str, *, page, config, files) -> str:
    post = _post_by_source.get(page.file.src_uri)
    landing = _landing_by_source.get(page.file.src_uri)
    if post:
        page.meta["title"] = post["title"]
        page.meta["date"] = post["date"]
        page.meta.setdefault("description", post["summary"])
    elif landing:
        page.meta["template"] = "topic.html"
        page.meta["title"] = landing["title"]
        page.meta["description"] = landing["description"]
        page.meta["comments"] = False
        page.meta["search"] = {"exclude": True}
    return markdown


def on_page_context(context: dict, *, page, config, nav) -> dict:
    post = _post_by_source.get(page.file.src_uri)
    series_posts: list[dict] = []
    previous = following = None
    if post:
        if post["series"]:
            series_posts = sorted(
                [candidate for candidate in _posts if candidate["category_id"] == post["category_id"] and candidate["series"] == post["series"]],
                key=_series_sort,
            )
        siblings = series_posts or [candidate for candidate in _posts if candidate["category_id"] == post["category_id"]]
        position = siblings.index(post)
        previous = siblings[position - 1] if position > 0 else None
        following = siblings[position + 1] if position + 1 < len(siblings) else None
    context.update(
        blog_posts=_posts,
        blog_topics=_topics,
        blog_categories=_categories,
        blog_archives=_archives,
        blog_post=post,
        blog_topic=_landing_by_source.get(page.file.src_uri),
        blog_series_posts=series_posts,
        blog_prev=previous,
        blog_next=following,
        posts_count=len(_posts),
    )
    return context
