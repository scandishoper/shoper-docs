"""Synthetic fixtures for importing and displaying the previous blog's comments."""

from __future__ import annotations

from copy import deepcopy
from html.parser import HTMLParser
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import tempfile
import unittest
from urllib.parse import quote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class HTMLShape(HTMLParser):
    def __init__(self, value):
        super().__init__()
        self.elements = []
        self.feed(str(value))

    def handle_starttag(self, tag, attributes):
        self.elements.append((tag, dict(attributes)))


class LegacyCommentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.importer = load_module("comment_import_under_test", "scripts/import_legacy_comments.py")
        cls.renderer = load_module("comment_render_under_test", "hooks/comments.py")

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="shoper-comments-test-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.docs = self.project / "docs"
        (self.docs / "blog").mkdir(parents=True)
        (self.docs / "technology").mkdir()
        (self.docs / "blog/post.md").write_text("# Article\n", encoding="utf-8")
        (self.docs / "technology/post.md").write_text("# Technical article\n", encoding="utf-8")
        self.original_path = "/2025/02/19/原文章/"
        self.path_map = {self.original_path: "blog/post.md"}

    def raw(self, identity="first", **overrides):
        row = {
            "objectId": identity,
            "nick": "  示例 Reader  ",
            "comment": "Original text\n\n  **Preserved exactly** :longing:",
            "createdAt": "2025-02-19T15:59:59.500Z",
            "insertedAt": {"__type": "Date", "iso": "2025-02-19T16:00:01.123Z"},
            "updatedAt": "2025-03-01T00:00:00.000Z",
            "url": self.original_path,
            "mail": "synthetic-private@example.test",
            "ip": "192.0.2.123",
            "ua": "SYNTHETIC_PRIVATE_AGENT",
            "ACL": {"SYNTHETIC_PRIVATE_OWNER": {"read": True}},
        }
        row.update(overrides)
        return row

    def migrate(self, rows, path_map=None):
        return self.importer.migrate_comments(rows, path_map or self.path_map, self.docs)

    def test_export_reads_only_comment_streams_without_extracting_archive_paths(self):
        archive_path = self.project / "export.tar.gz"
        header = '#filetype:JSON-streaming {"type":"Class","class":"Comment"}\n'
        entries = {
            "export/Comment.0.jsonl": header + json.dumps(self.raw("first")) + "\n\n",
            "export/Comment.1.jsonl": header + json.dumps(self.raw("second")) + "\n",
            "export/_User.0.jsonl": "THIS SYSTEM TABLE MUST NOT BE READ",
            "export/Commentary.0.jsonl": "THIS IS NOT THE COMMENT TABLE",
            "../../Comment.0.jsonl": "DO NOT READ A TRAVERSAL MEMBER",
            "/Comment.2.jsonl": "DO NOT READ AN ABSOLUTE MEMBER",
        }
        with tarfile.open(archive_path, "w:gz") as archive:
            for name, content in entries.items():
                blob = content.encode("utf-8")
                member = tarfile.TarInfo(name)
                member.size = len(blob)
                archive.addfile(member, io.BytesIO(blob))

        rows = self.importer.read_export(archive_path)
        self.assertEqual(sorted(row["objectId"] for row in rows), ["first", "second"])
        self.assertFalse((self.project / "export").exists())
        self.assertFalse((self.project / "Comment.2.jsonl").exists())

    def test_migration_preserves_public_values_and_is_private_and_repeatable(self):
        rows = [self.raw()]
        original = deepcopy(rows)
        result = self.migrate(rows)
        record = result["comments"][0]
        self.assertEqual(result["version"], 1)
        self.assertEqual(set(record), {
            "id", "author", "body", "created_at", "published_at", "source",
            "original_path", "parent_id", "root_id",
        })
        self.assertEqual(record["id"], rows[0]["objectId"])
        self.assertEqual(record["author"], rows[0]["nick"])
        self.assertEqual(record["body"], rows[0]["comment"])
        self.assertEqual(record["created_at"], rows[0]["createdAt"])
        self.assertEqual(record["published_at"], rows[0]["insertedAt"]["iso"])
        self.assertIsNone(record["parent_id"])
        self.assertIsNone(record["root_id"])
        serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
        for private_value in ("synthetic-private@example.test", "192.0.2.123",
                              "SYNTHETIC_PRIVATE_AGENT", "SYNTHETIC_PRIVATE_OWNER"):
            self.assertNotIn(private_value, serialized)
        self.assertEqual(rows, original)
        self.assertEqual(serialized, json.dumps(self.migrate(rows), ensure_ascii=False, sort_keys=True))

    def test_standalone_json_supports_formatted_arrays_and_result_objects(self):
        rows = [self.raw("one"), self.raw("two")]
        export = self.project / "Comment.json"
        for payload in (rows, {"results": rows}):
            with self.subTest(format=type(payload).__name__):
                export.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                self.assertEqual(self.importer.read_export(export), rows)

    def test_chinese_percent_encoded_routes_preserve_literal_cplusplus(self):
        old_path = "/2025/03/02/C++ 核心编程/"
        encoded_path = quote(old_path, safe="/+")
        result = self.migrate([self.raw(url=encoded_path)], {old_path: "technology/post.md"})
        record = result["comments"][0]
        self.assertEqual(record["source"], "technology/post.md")
        self.assertIn("C++", record["original_path"])

    def test_display_uses_inserted_time_in_beijing_and_missing_inserted_time_falls_back(self):
        row = self.raw()
        records = self.migrate([row])["comments"]
        node = self.renderer.build_threads(records)[0]
        self.assertEqual(node["created_at"], row["insertedAt"]["iso"])
        displayed = [int(value) for value in re.findall(r"\d+", node["date_display"])]
        self.assertEqual(displayed[:5], [2025, 2, 20, 0, 0])

        row.pop("insertedAt")
        record = self.migrate([row])["comments"][0]
        self.assertEqual(record["published_at"], row["createdAt"])

    def test_invalid_identifiers_routes_targets_and_dates_are_rejected(self):
        cases = [
            ("duplicate", [self.raw(), self.raw()], self.path_map),
            ("unmapped", [self.raw(url="/unknown/")], self.path_map),
            ("missing target", [self.raw()], {self.original_path: "blog/missing.md"}),
            ("invalid created date", [self.raw(createdAt="2025-02-30T12:00:00Z")], self.path_map),
            ("invalid inserted date", [self.raw(insertedAt={"__type": "Date", "iso": "invalid"})], self.path_map),
        ]
        for name, rows, mapping in cases:
            with self.subTest(case=name), self.assertRaises(ValueError):
                self.migrate(rows, mapping)
        (self.project / "outside.md").write_text("Outside docs", encoding="utf-8")
        with self.assertRaises(ValueError):
            self.migrate([self.raw()], {self.original_path: "../outside.md"})

    def test_reply_chain_preserves_ids_and_renders_under_its_parent(self):
        rows = [
            self.raw("root", nick="Root"),
            self.raw("child", nick="Child", pid="root", rid="root"),
            self.raw("grandchild", nick="Grandchild", pid="child", rid="root"),
        ]
        records = self.migrate(rows)["comments"]
        by_id = {record["id"]: record for record in records}
        self.assertEqual(by_id["grandchild"]["parent_id"], "child")
        self.assertEqual(by_id["grandchild"]["root_id"], "root")
        threads = self.renderer.build_threads(records)
        self.assertEqual([node["id"] for node in threads], ["root"])
        child = threads[0]["children"][0]
        self.assertEqual(child["id"], "child")
        self.assertEqual(child["children"][0]["id"], "grandchild")
        self.assertEqual(child["reply_to"], "Root")
        self.assertEqual(child["children"][0]["reply_to"], "Child")

    def test_orphan_reply_is_retained_and_marked_instead_of_disappearing(self):
        records = self.migrate([self.raw("orphan", pid="missing", rid="missing")])["comments"]
        self.assertEqual(records[0]["parent_id"], "missing")
        threads = self.renderer.build_threads(records)
        self.assertEqual([node["id"] for node in threads], ["orphan"])
        self.assertIn("原评论已缺失", json.dumps(threads, ensure_ascii=False))

    def test_circular_replies_are_rejected_before_publication(self):
        cases = [
            [self.raw("self", pid="self", rid="self")],
            [self.raw("a", pid="b", rid="b"), self.raw("b", pid="a", rid="a")],
        ]
        for rows in cases:
            with self.subTest(ids=[row["objectId"] for row in rows]), self.assertRaises(ValueError):
                self.migrate(rows)

    def test_rendering_keeps_safe_markdown_and_known_emojis_without_active_injection(self):
        rendered = str(self.renderer.render_body(
            '<script>alert("unsafe")</script><img src=x onerror="alert(1)">\n\n'
            '[unsafe](javascript:alert(1)) [safe](https://example.test/path)\n\n'
            '**Readable** :longing: :tv_亲亲: :tv_doge: :unknown_emoji:\n\n'
            '`literal :longing:`'
        ))
        elements = HTMLShape(rendered).elements
        self.assertNotIn("script", [tag for tag, _ in elements])
        self.assertIn("strong", [tag for tag, _ in elements])
        self.assertIn(":unknown_emoji:", rendered)
        self.assertIn("literal :longing:", rendered)
        for tag, attributes in elements:
            self.assertFalse(any(key.lower().startswith("on") for key in attributes))
            for attribute in ("href", "src"):
                if attribute in attributes:
                    self.assertIn(urlsplit(attributes[attribute]).scheme, ("http", "https"))
        images = [attributes["src"] for tag, attributes in elements if tag == "img"]
        self.assertEqual(set(images), {
            "https://img.t.sinajs.cn/t4/appstyle/expression/ext/normal/c9/2018new_chongjing_org.png",
            "https://i0.hdslb.com/bfs/emote/a8111ad55953ef5e3be3327ef94eb4a39d535d06.png",
            "https://i0.hdslb.com/bfs/emote/6ea59c827c414b4a2955fe79e0f6fd3dcd515e24.png",
        })
        self.assertEqual(len(images), 3)


if __name__ == "__main__":
    unittest.main()
