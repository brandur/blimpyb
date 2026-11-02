#!/usr/bin/env python3
"""Verify every generated local link, image, and active content boundary."""
from pathlib import Path
import hashlib
import json
from urllib.parse import unquote, urlsplit
from bs4 import BeautifulSoup
from PIL import Image
from recover import ROOT


def check(directory):
    errors = []
    pages = list(directory.rglob("*.html"))
    for path in pages:
        soup = BeautifulSoup(path.read_text(), "html.parser")
        for tag in soup.find_all(True):
            if tag.name in {"iframe", "object", "embed", "base"}:
                errors.append(f"{path}: active archived element {tag.name}")
            for attr in ["href", "src"]:
                if not tag.has_attr(attr):
                    continue
                url = urlsplit(tag[attr])
                if url.scheme or url.netloc:
                    if attr == "src" or url.scheme not in {"https", "http", "mailto"}:
                        errors.append(f"{path}: unexpected remote/active resource {tag[attr]}")
                    continue
                if not url.path:
                    continue
                target = (path.parent / unquote(url.path)).resolve()
                if not target.is_relative_to(directory.resolve()) or not target.is_file():
                    errors.append(f"{path}: broken local {attr}: {tag[attr]}")
            if tag.name == "img" and not tag.has_attr("alt"):
                errors.append(f"{path}: image without alt attribute")
        if not soup.select_one("main#main") or not soup.find("h1"):
            errors.append(f"{path}: missing page landmark or title")
    for path in [*(directory / "images").iterdir(), *(ROOT / "archive/assets").iterdir()]:
        try:
            with Image.open(path) as img:
                img.verify()
            with Image.open(path) as img:
                img.load()
        except Exception as exc:
            errors.append(f"{path}: invalid image: {exc}")
    for name in ["pages", "feeds", "images", "map"]:
        manifest = ROOT / "archive" / f"{name}.json"
        if not manifest.exists():
            continue
        data = json.loads(manifest.read_text())
        records = [data] if name == "map" else data.values()
        for record in records:
            if record.get("status", "ok") != "ok":
                continue
            path = ROOT / record["path"]
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                errors.append(f"{path}: missing file or preservation hash mismatch")
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"Verified {len(pages)} pages: local links resolve, images decode, no remote embedded resources")


if __name__ == "__main__":
    check(ROOT / "dist")
