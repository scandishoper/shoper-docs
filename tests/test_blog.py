"""Exercise publishing through MkDocs, using disposable Markdown fixtures.

Run with ``python -m unittest discover -s tests -v`` after installing the
project's requirements. These tests never create or alter real blog articles.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from html.parser import HTMLParser
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import unquote, urljoin, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[1]


class PostLinks(HTMLParser):
    """Read links from one component, excluding unrelated page navigation."""

    def __init__(self, html: str, page_url: str, container_class="paper-post-row"):
        super().__init__()
        self.page_url = page_url
        self.container_class = container_class
        self.links: list[str] = []
        self.titles: dict[str, str] = {}
        self.anchor: tuple[str, list[str]] | None = None
        self.stack: list[tuple[str, bool]] = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        in_row = any(is_row for _, is_row in self.stack)
        is_row = self.container_class in attrs.get("class", "").split()
        if tag == "a" and in_row and "href" in attrs:
            path = urlsplit(urljoin(self.page_url, attrs["href"])).path
            path = unquote(path).lstrip("/")
            self.links.append(path)
            self.anchor = (path, [])
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img",
                       "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append((tag, is_row))

    def handle_endtag(self, tag):
        if tag == "a" and self.anchor:
            path, text = self.anchor
            self.titles[path] = " ".join("".join(text).split())
            self.anchor = None
        for position in range(len(self.stack) - 1, -1, -1):
            if self.stack[position][0] == tag:
                del self.stack[position:]
                return

    def handle_data(self, data):
        if self.anchor:
            self.anchor[1].append(data)


class AutomaticPublishingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="shoper-blog-test-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.docs = self.project / "docs"
        self.site = self.project / "site"
        self.docs.mkdir()
        (self.project / "hooks").mkdir()
        shutil.copy2(ROOT / "hooks" / "blog.py", self.project / "hooks" / "blog.py")
        self.write("index.md", "---\ntemplate: home.html\n---\n# Test blog\n")
        configuration = {
            "site_name": "Publishing test",
            "site_url": "https://example.test/",
            "docs_dir": "docs",
            "site_dir": "site",
            "theme": {
                "name": "material",
                "custom_dir": str(ROOT / "overrides"),
                "language": "zh",
            },
            "markdown_extensions": ["pymdownx.superfences"],
            "plugins": [{"search": {"lang": "en"}}],
            "hooks": ["hooks/blog.py"],
            "nav": [
                {"Home": "index.md"},
                {"Archive": "archive.md"},
                {"Topics": "topics.md"},
            ],
        }
        self.config_path = self.project / "mkdocs.yml"
        self.config_path.write_text(
            yaml.safe_dump(configuration, allow_unicode=True), encoding="utf-8"
        )

    def write(self, relative_path: str, content: str) -> Path:
        path = self.docs / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def build(self):
        result = subprocess.run(
            [sys.executable, "-m", "mkdocs", "build", "--strict",
             "--config-file", str(self.config_path)],
            cwd=self.project,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "CI": "false", "PYTHONUTF8": "1"},
            timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def html(self, url: str) -> str:
        return (self.site / url / "index.html").read_text(encoding="utf-8")

    def links(self, url: str, container_class="paper-post-row") -> list[str]:
        return PostLinks(self.html(url), "https://example.test/" + url, container_class).links

    def titles(self, url: str) -> dict[str, str]:
        return PostLinks(self.html(url), "https://example.test/" + url).titles

    def search_locations(self) -> set[str]:
        search = json.loads((self.site / "search/search_index.json").read_text("utf-8"))
        return {unquote(item["location"].split("#", 1)[0]) for item in search["docs"]}

    def test_new_markdown_is_discovered_without_editing_navigation(self):
        original_config = self.config_path.read_bytes()
        articles = [
            ("algo/p1.md", "algorithms", "Original article"),
            ("solutions/contest/任意新题解.md", "algorithms", "嵌套题解"),
            ("csdiy/course/chapter-one.md", "cs", "Nested course note"),
            ("technology/arbitrary-name.md", "technology", "Technical article"),
            ("views/a-new-view.md", "life", "New view"),
            ("blog/diary/new-diary.md", "life", "Nested diary"),
        ]
        for number, (path, _, title) in enumerate(articles, start=1):
            self.write(path, f"---\ntitle: {title}\ndate: 2099-01-{number:02}\n---\nBody.\n")

        self.build()
        self.assertEqual(self.config_path.read_bytes(), original_config)
        locations = self.search_locations()
        for path, topic, title in articles:
            with self.subTest(path=path):
                url = path.removesuffix(".md") + "/"
                category = path.split("/", 1)[0]
                self.assertIn(url, self.links(""))
                self.assertIn(url, self.links("archive/"))
                self.assertIn(url, self.links(f"topics/{topic}/"))
                self.assertIn(url, self.links(category + "/"))
                self.assertIn(url, locations)
                self.assertIn(title, self.html(url))
        # The existing path, including the old pN slug, remains the published URL.
        self.assertTrue((self.site / "algo/p1/index.html").is_file())

    def test_dates_sort_chronologically_and_plain_markdown_has_fallbacks(self):
        self.write("algo/dotted-date.md", "---\ntitle: Dotted date\ndate: 2026.10.2\n---\nBody.\n")
        self.write("algo/iso-date.md", "---\ntitle: ISO date\ndate: 2026-09-30\n---\nBody.\n")
        heading = self.write("algo/heading.md", "```markdown\n# Example, not the title\n```\n\n# Title from heading\n\nBody.\n")
        filename = self.write("algo/filename.md", "No heading or metadata here.\n")
        fallback = datetime(2001, 2, 3, 12, tzinfo=timezone.utc).timestamp()
        os.utime(heading, (fallback, fallback))
        os.utime(filename, (fallback, fallback))

        self.build()
        for listing in ("", "archive/", "topics/algorithms/", "algo/"):
            links = self.links(listing)
            self.assertLess(links.index("algo/dotted-date/"), links.index("algo/iso-date/"))
            self.assertLess(links.index("algo/iso-date/"), links.index("algo/heading/"))
        self.assertIn("Title from heading", self.html("algo/heading/"))
        titles = self.titles("archive/")
        self.assertEqual(titles["algo/heading/"], "Title from heading")
        self.assertEqual(titles["algo/filename/"], "filename")
        self.assertIn('datetime="2001-02-03"', self.html("algo/heading/"))
        self.assertIn('datetime="2001-02-03"', self.html("algo/filename/"))
        before = self.links("archive/")
        self.build()
        self.assertEqual(self.links("archive/"), before)
        self.assertIn('datetime="2001-02-03"', self.html("algo/heading/"))

    @unittest.skipUnless(shutil.which("git"), "Git is needed to check publication history")
    def test_undated_post_keeps_original_git_date_after_rename_and_checkout(self):
        self.write("algo/first-name.md", "# A historical article\n\nBody.\n")

        def git(*arguments, timestamp="2002-03-04T12:00:00+00:00"):
            result = subprocess.run(
                ["git", "-c", "user.name=Blog integration test",
                 "-c", "user.email=blog-test@example.test", "-c", "commit.gpgsign=false",
                 "-c", f"core.hooksPath={self.project / 'no-hooks'}", *arguments],
                cwd=self.project,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={**os.environ, "GIT_AUTHOR_DATE": timestamp, "GIT_COMMITTER_DATE": timestamp},
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        git("init", "--quiet")
        git("add", "docs/algo/first-name.md")
        git("commit", "--quiet", "-m", "Initial publication")
        git("mv", "docs/algo/first-name.md", "docs/algo/renamed.md")
        git("commit", "--quiet", "-m", "Rename the article", timestamp="2005-06-07T12:00:00+00:00")
        checkout_time = datetime(2099, 1, 1, 12, tzinfo=timezone.utc).timestamp()
        os.utime(self.docs / "algo/renamed.md", (checkout_time, checkout_time))

        self.build()
        self.assertIn('datetime="2002-03-04"', self.html("algo/renamed/"))
        self.assertNotIn('datetime="2099-01-01"', self.html("algo/renamed/"))

    def test_drafts_and_removed_or_renamed_articles_leave_no_published_remnants(self):
        for slug in ("rename-me", "delete-me", "make-draft"):
            self.write(f"technology/{slug}.md", f"---\ntitle: {slug}\ndate: 2026-03-04\n---\nBody.\n")
        self.write("technology/never-publish.md", "---\ntitle: Secret draft\ndraft: true\n---\nPrivate draft body.\n")
        self.build()
        self.assertFalse((self.site / "technology/never-publish/index.html").exists())
        self.assertNotIn("technology/never-publish/", self.search_locations())
        self.assertNotIn("Secret draft", self.html("archive/"))
        search_json = (self.site / "search/search_index.json").read_text("utf-8")
        self.assertNotIn("Secret draft", search_json)
        self.assertNotIn("Private draft body", search_json)

        (self.docs / "technology/rename-me.md").rename(self.docs / "technology/renamed.md")
        (self.docs / "technology/delete-me.md").unlink()
        self.write("technology/make-draft.md", "---\ntitle: Previously public\ndraft: true\n---\nBody.\n")
        self.build()

        locations = self.search_locations()
        for stale in ("rename-me", "delete-me", "make-draft", "never-publish"):
            with self.subTest(stale=stale):
                url = f"technology/{stale}/"
                self.assertFalse((self.site / url / "index.html").exists())
                self.assertNotIn(url, locations)
                for listing in ("", "archive/", "topics/technology/", "technology/"):
                    self.assertNotIn(url, self.links(listing))
        self.assertIn("technology/renamed/", locations)
        self.assertIn("technology/renamed/", self.links("topics/technology/"))

    def test_series_order_and_previous_next_follow_chapters_instead_of_dates(self):
        chapters = ["csdiy/course/first/", "csdiy/course/second/", "csdiy/course/third/"]
        for order, (slug, day) in enumerate((("first", 3), ("second", 1), ("third", 2)), start=1):
            self.write(
                f"csdiy/course/{slug}.md",
                f"---\ntitle: Chapter {order}\ndate: 2026-01-{day:02}\nseries: Course\norder: {order}\n---\nBody.\n",
            )
        self.write("csdiy/other.md", "---\ntitle: Another series\ndate: 2099-01-01\nseries: Different course\n---\nBody.\n")
        self.build()

        for listing in ("topics/cs/", "csdiy/"):
            self.assertEqual([url for url in self.links(listing) if url in chapters], chapters)
        for chapter in chapters:
            self.assertEqual(self.links(chapter, "paper-series"), chapters)
        self.assertEqual(self.links(chapters[0], "paper-pagination"), [chapters[1]])
        self.assertEqual(self.links(chapters[1], "paper-pagination"), [chapters[0], chapters[2]])
        self.assertEqual(self.links(chapters[2], "paper-pagination"), [chapters[1]])

    def test_enabled_encryption_does_not_expose_body_in_lists_or_search(self):
        configuration = yaml.safe_load(self.config_path.read_text("utf-8"))
        configuration["plugins"].append({"encryptcontent": {
            "enabled": True,
            "global_password": "",
            "search_index": "encrypted",
        }})
        self.config_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
        body_marker = "PRIVATE_BODY_SENTINEL_847291"
        self.write(
            "technology/protected.md",
            "---\ntitle: Protected fixture\ndate: 2026-03-04\n"
            "password: temporary-fixture-password-9vHaZ7!\n---\n"
            f"{body_marker}\n",
        )
        self.build()

        # Only the explicitly enabled encryption mode is covered. A password
        # field alone does not enable this optional MkDocs plugin.
        self.assertTrue((self.site / "technology/protected/index.html").exists())
        self.assertIn("Protected fixture", self.html("archive/"))
        for html_file in self.site.rglob("*.html"):
            self.assertNotIn(body_marker, html_file.read_text("utf-8"), str(html_file))
        self.assertNotIn(body_marker, (self.site / "search/search_index.json").read_text("utf-8"))
        self.assertNotIn("technology/protected/", self.search_locations())


class DateParsingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("blog_under_test", ROOT / "hooks/blog.py")
        cls.hook = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = cls.hook
        spec.loader.exec_module(cls.hook)

    def test_supported_dates_and_invalid_values(self):
        for value in ("2026.3.4", "2026-03-04", date(2026, 3, 4),
                      datetime(2026, 3, 4, 12, 30)):
            with self.subTest(value=value):
                self.assertEqual(self.hook.parse_date(value), date(2026, 3, 4))
        for value in (None, "", "not a date", "2026.2.30", "2026-13-01"):
            with self.subTest(value=value):
                self.assertIsNone(self.hook.parse_date(value))


if __name__ == "__main__":
    unittest.main()
