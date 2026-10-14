"""Import only public comment fields from a local LeanCloud export.

The original export stays outside the repository. Nothing is extracted to disk,
and system tables (which can contain credentials) are never opened.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


def _read_records(text: str) -> list[dict]:
    text = text.lstrip("\ufeff").strip()
    if not text:
        return []
    lines = [line for line in text.splitlines() if line.strip() and not line.startswith("#filetype:")]
    try:
        value = json.loads("\n".join(lines))
        records = value.get("results", [value]) if isinstance(value, dict) else value
    except json.JSONDecodeError:
        records = [json.loads(line) for line in lines]
    if not isinstance(records, list) or any(not isinstance(record, dict) for record in records):
        raise ValueError("Expected a list of Comment records")
    return records


def read_export(path: Path) -> list[dict]:
    """Read Comment shards in memory; never unpack or read other tables."""
    path = Path(path)
    if tarfile.is_tarfile(path):
        rows = []
        with tarfile.open(path, "r:*") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                if not member.isfile() or name.is_absolute() or ".." in name.parts:
                    continue
                if not re.fullmatch(r"Comment(?:\.\d+)?\.jsonl?", name.name):
                    continue
                if member.size > 50_000_000:
                    raise ValueError("Comment shard is unexpectedly large")
                with archive.extractfile(member) as stream:
                    rows.extend(_read_records(stream.read().decode("utf-8-sig")))
        if not rows:
            raise ValueError("No Comment records found in the export")
        return rows
    return _read_records(path.read_text(encoding="utf-8-sig"))


def normalized_path(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.netloc and parsed.hostname != "blog.scandidreams.top":
        raise ValueError("Comment URL belongs to a different website")
    path = unquote(parsed.path)
    if not path.startswith("/") or ".." in PurePosixPath(path).parts:
        raise ValueError("Invalid original comment path")
    return path


def _date(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("Comment timestamp must be an ISO string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Invalid comment timestamp") from error
    if parsed.tzinfo is None:
        raise ValueError("Comment timestamp must include its timezone")
    return parsed


def migrate_comments(rows: list[dict], path_map: dict[str, str], docs_dir: Path) -> dict:
    """Validate a complete import, keeping the exact text and both timestamps."""
    docs_dir = Path(docs_dir).resolve()
    mapping = {normalized_path(path): source for path, source in path_map.items()}
    records = []
    ids = set()
    for row in rows:
        identifier = row.get("objectId")
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identifier):
            raise ValueError("Invalid comment ID")
        if identifier in ids:
            raise ValueError(f"Duplicate comment ID: {identifier}")
        ids.add(identifier)
        original_path = normalized_path(row.get("url", ""))
        if original_path not in mapping:
            raise ValueError(f"Comment path has no reviewed mapping: {original_path}")
        source = mapping[original_path]
        target = (docs_dir / source).resolve()
        if not target.is_relative_to(docs_dir) or not target.is_file() or target.suffix != ".md":
            raise ValueError(f"Missing or invalid target Markdown: {source}")
        author, body = row.get("nick"), row.get("comment")
        if not isinstance(author, str) or not isinstance(body, str):
            raise ValueError(f"Invalid public text fields in comment {identifier}")
        created = row.get("createdAt")
        inserted = row.get("insertedAt")
        published = inserted.get("iso") if isinstance(inserted, dict) else inserted
        published = created if published is None else published
        _date(created)
        _date(published)
        # Explicit allowlist: mail, IP, user-agent, ACL and other private fields
        # must never enter a public repository or the rendered site.
        record = {
            "id": identifier,
            "author": author,
            "body": body,
            "created_at": created,
            "published_at": published,
            "source": source,
            "original_path": original_path,
            "parent_id": row.get("pid") or None,
            "root_id": row.get("rid") or None,
        }
        for field in ("parent_id", "root_id"):
            if record[field] is not None and not isinstance(record[field], str):
                raise ValueError(f"Invalid reply ID in comment {identifier}")
        records.append(record)

    by_id = {record["id"]: record for record in records}
    for record in records:
        for field in ("parent_id", "root_id"):
            ancestor = by_id.get(record[field])
            if ancestor and (ancestor["source"], ancestor["original_path"]) != (record["source"], record["original_path"]):
                raise ValueError(f"Reply crosses original pages: {record['id']}")
        visited = {record["id"]}
        parent = record["parent_id"]
        while parent in by_id:
            if parent in visited:
                raise ValueError(f"Cyclic reply chain: {record['id']}")
            visited.add(parent)
            parent = by_id[parent]["parent_id"]
    records.sort(key=lambda item: (item["source"], _date(item["created_at"]), item["id"]))
    return {"version": 1, "comments": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export", type=Path, help="Local .tar.gz or Comment.jsonl export")
    parser.add_argument("--mapping", type=Path, default=ROOT / "data/legacy-comment-paths.json")
    parser.add_argument("--docs-dir", type=Path, default=ROOT / "docs")
    parser.add_argument("--output", type=Path, default=ROOT / "data/legacy-comments.json")
    args = parser.parse_args()
    data = migrate_comments(read_export(args.export), json.loads(args.mapping.read_text(encoding="utf-8")), args.docs_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    temporary.replace(args.output)
    counts = Counter(item["source"] for item in data["comments"])
    print(f"Imported {len(data['comments'])} comments, {sum(bool(item['parent_id']) for item in data['comments'])} replies")
    for source, count in sorted(counts.items()):
        print(f"  {source}: {count}")


if __name__ == "__main__":
    main()
