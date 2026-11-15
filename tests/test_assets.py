"""Prevent stale CSS/JS from being reused after a blog deployment."""

from __future__ import annotations

from html.parser import HTMLParser
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urljoin, urlsplit

from mkdocs.config import load_config
from mkdocs.structure.files import get_files
import yaml


ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://example.test/notebook/"
REMOTE_CSS = "https://cdn.example.test/theme.css?v=2"
REMOTE_JS = "https://cdn.example.test/math.js?v=3#startup"


class AssetLinks(HTMLParser):
    def __init__(self, html: str):
        super().__init__()
        self.styles: list[str] = []
        self.scripts: list[dict] = []
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.styles.append(attrs["href"])
        if tag == "script" and "src" in attrs:
            self.scripts.append(attrs)


class AssetPublishingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="shoper-assets-test-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.docs = self.project / "docs"
        self.site = self.project / "site"
        self.docs.mkdir()
        (self.project / "hooks").mkdir()
        shutil.copy2(ROOT / "hooks/assets.py", self.project / "hooks/assets.py")
        self.sources = {
            "stylesheets/paper.css": b"/* journal */ body { color: #315a46; }\n",
            "javascripts/paper.js": 'window.journal = "你好";\n'.encode("utf-8"),
            "javascripts/reader.mjs": b"export const reader = true;\n",
        }
        for path, content in self.sources.items():
            self.write(path, content)
        self.write("index.md", b"# Journal\n")
        self.write("nested/article.md", b"# Reading\n")
        self.config_path = self.project / "mkdocs.yml"
        self.config_path.write_text(yaml.safe_dump({
            "site_name": "Asset publishing test",
            "site_url": SITE_URL,
            "docs_dir": "docs",
            "site_dir": "site",
            "theme": {"name": "material", "font": False},
            "plugins": ["search", {"minify": {"minify_html": True}}],
            "hooks": ["hooks/assets.py"],
            "extra_css": ["stylesheets/paper.css?theme=reading#paint", REMOTE_CSS],
            "extra_javascript": [
                "javascripts/paper.js",
                {"path": "javascripts/reader.mjs", "type": "module", "defer": True},
                REMOTE_JS,
            ],
        }), encoding="utf-8")

    def write(self, path: str, content: bytes):
        destination = self.docs / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)

    def test_minified_pages_load_matching_assets_at_root_nested_and_404_urls(self):
        result = subprocess.run(
            [sys.executable, "-m", "mkdocs", "build", "--strict",
             "--config-file", str(self.config_path)],
            cwd=self.project, capture_output=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONUTF8": "1"}, timeout=90,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        shared_urls = None
        for output, location in (
            ("index.html", SITE_URL),
            ("nested/article/index.html", SITE_URL + "nested/article/"),
            ("404.html", SITE_URL + "missing/deep/page/"),
        ):
            with self.subTest(page=output):
                links = AssetLinks((self.site / output).read_text("utf-8"))
                self.assertIn(REMOTE_CSS, links.styles)
                self.assertIn(REMOTE_JS, [script["src"] for script in links.scripts])
                css = next(url for url in links.styles if "/paper." in url)
                scripts = [script for script in links.scripts
                           if "/paper." in script["src"] or "/reader." in script["src"]]
                self.assertEqual(len(scripts), 2)
                references = [css, *(script["src"] for script in scripts)]
                resolved = [urljoin(location, reference) for reference in references]
                if shared_urls is None:
                    shared_urls = resolved
                self.assertEqual(resolved, shared_urls)
                for source, url in zip(self.sources, resolved):
                    target = urlsplit(url)
                    self.assertEqual(target.netloc, "example.test")
                    self.assertTrue(target.path.startswith("/notebook/"))
                    path = target.path.removeprefix("/notebook/")
                    self.assertNotEqual(path, source)
                    self.assertEqual(Path(path).parent, Path(source).parent)
                    self.assertEqual((self.site / path).read_bytes(), self.sources[source])
                self.assertEqual(urlsplit(css).query, "theme=reading")
                self.assertEqual(urlsplit(css).fragment, "paint")
                module = next(script for script in scripts if "/reader." in script["src"])
                self.assertEqual(module["type"], "module")
                self.assertIn("defer", module)
        # Old page copies can still request the original URLs.
        for source, content in self.sources.items():
            self.assertEqual((self.site / source).read_bytes(), content)
            self.assertEqual((self.docs / source).read_bytes(), content)

    def test_live_rebuild_changes_only_modified_asset_urls_and_preserves_script_options(self):
        config = load_config(str(self.config_path))
        config.plugins.on_config(config)

        def rebuild():
            files = get_files(config)
            return config.plugins.on_files(files, config=config)

        files = rebuild()
        original_css = config.extra_css[0]
        original_js = [str(script) for script in config.extra_javascript]
        rebuild()
        self.assertEqual(config.extra_css[0], original_css)
        self.assertEqual([str(script) for script in config.extra_javascript], original_js)

        changed = b"body { color: #a7c6a7; }\n"
        self.write("stylesheets/paper.css", changed)
        files = rebuild()
        changed_css = config.extra_css[0]
        self.assertNotEqual(changed_css, original_css)
        self.assertEqual([str(script) for script in config.extra_javascript], original_js)
        self.assertEqual(files.get_file_from_path(urlsplit(changed_css).path).content_bytes, changed)
        self.assertEqual(config.extra_css[1], REMOTE_CSS)
        self.assertEqual(config.extra_javascript[-1], REMOTE_JS)
        self.assertEqual(config.extra_javascript[1].type, "module")
        self.assertTrue(config.extra_javascript[1].defer)

        self.write("stylesheets/paper.css", self.sources["stylesheets/paper.css"])
        rebuild()
        self.assertEqual(config.extra_css[0], original_css)


if __name__ == "__main__":
    unittest.main()
