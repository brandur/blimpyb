#!/usr/bin/env python3
"""Resumable, non-destructive recovery from the Wayback CDX inventory.

Raw responses are retained separately from the hand-edited Markdown archive.
Only historic blog routes and image assets are selected, never the later spam.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit, urlencode, urljoin, parse_qs

from bs4 import BeautifulSoup
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "archive"
REQUEST_LOCK = threading.Lock()
LAST_REQUEST = 0.0
REQUEST_DELAY = 5.0
CDX_URL = "https://web.archive.org/cdx/search/cdx?" + urlencode({
    "url": "blimpyb.com/*", "output": "json", "filter": "statuscode:200",
    "collapse": "urlkey", "to": "2016",
})


def original_url(url):
    url = re.sub(r"^https?://web\.archive\.org/web/[^/]+/", "", url)
    return url.replace("blimpyb.com:80", "blimpyb.com")


def url_key(url):
    p = urlsplit(original_url(url))
    return (p.hostname or "").removeprefix("www.") + unquote(p.path).rstrip("/") + ("?" + p.query if p.query else "")


def article_id(url):
    p = urlsplit(original_url(url))
    if p.hostname not in {"blimpyb.com", "www.blimpyb.com"}:
        return None
    short_id = parse_qs(p.query).get("p", [""])[0]
    if p.path in {"", "/"} and short_id.isdigit():
        return short_id
    match = re.fullmatch(r"/(?!date/|page/|category/|tag/|gallery/|wp)(?:[^/]+/)+([0-9]+)/?", p.path)
    return match[1] if match else None


def image_family(url):
    """Match only the same upload path, allowing WP sizes and PageSpeed variants."""
    key = url_key(url).split("?", 1)[0]
    directory, _, name = key.rpartition("/")
    if ".pagespeed." in name:
        name = name.split(".pagespeed.", 1)[0]
        name = re.sub(r"^(?:\d+x\d+x|x)", "", name)
    name = re.sub(r"-\d+x\d+(?=\.[^.]+$)", "", name)
    return directory + "/" + name


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def record_key(row):
    key = url_key(row["original"])
    return key + "@" + row["timestamp"] if row["kind"] == "feed" else key


def curl_with_info(url):
    global LAST_REQUEST
    with REQUEST_LOCK:
        time.sleep(max(0, REQUEST_DELAY - (time.monotonic() - LAST_REQUEST)))
        LAST_REQUEST = time.monotonic()
    for attempt in range(3):
        result = subprocess.run([
            "curl", "--silent", "--show-error", "--location", "--fail",
            "--connect-timeout", "15", "--max-time", "45",
            "--user-agent", "BlimpyB-Personal-Archive/1.0",
            "--write-out", "\n%{json}", url,
        ], capture_output=True)
        body, _, metadata = result.stdout.rpartition(b"\n")
        info = json.loads(metadata) if metadata else {}
        if not result.returncode:
            return body, info
        error = result.stderr.decode(errors="replace").strip()
        if attempt < 2 and (result.returncode in {7, 28} or info.get("http_code") in {429, 503}):
            # Wayback may refuse TCP connections while throttling. Stop requests
            # for five minutes instead of turning a temporary block into gaps.
            print("Archive unavailable; cooling down for five minutes", flush=True)
            with REQUEST_LOCK:
                time.sleep(310)
                LAST_REQUEST = time.monotonic()
        else:
            raise RuntimeError(error)
    raise RuntimeError(error)


def curl(url):
    return curl_with_info(url)[0]


def inventory():
    rows = json.loads((ARCHIVE / "indexes/wayback.json").read_text())
    return [dict(zip(rows[0], row)) for row in rows[1:]]


def targets(rows, phase):
    chosen = {}
    for row in rows:
        url = original_url(row["original"])
        p = urlsplit(url)
        is_image = row["mimetype"].startswith("image/") and (
            "/wp-content/uploads/" in p.path or "/themes/solarpress/images/" in p.path)
        is_page = row["mimetype"] == "text/html" and (
            article_id(url) or re.fullmatch(r"/gallery/[^/]+/", p.path)
            or re.fullmatch(r"/date/\d{4}/\d{2}/", p.path)
            or p.path in {"/about/", "/map/", "/contact/", "/gallery/"})
        if not (is_image if phase == "images" else is_page):
            continue
        key = url_key(url)
        chosen[key] = {**row, "original": url, "kind": "image" if is_image else "page"}
    if phase == "pages":
        # Keep the snapshots that underpinned the original, hand-edited archive.
        for path in (ROOT / "content/articles").glob("*.md"):
            m = re.search(r'wayback_machine_url = "https://web.archive.org/web/(\d+)/(.*?)"', path.read_text())
            if m:
                key = url_key(m[2])
                chosen[key] = {"timestamp": m[1], "original": original_url(m[2]), "kind": "page"}
        chosen["blimpyb.com"] = {"timestamp": "20140228064137", "original": "http://blimpyb.com/", "kind": "page"}
    values = list(chosen.values())
    if phase == "pages":
        values.sort(key=lambda r: (0 if article_id(r["original"]) else 1 if "/gallery/" in r["original"] else 2, r["original"]))
    else:
        # Recover pictures used in articles first; gallery-only images follow.
        references = set()
        manifest = ARCHIVE / "pages.json"
        if manifest.exists():
            for record in json.loads(manifest.read_text()).values():
                if record["status"] == "ok" and article_id(record["original"]):
                    soup = BeautifulSoup((ROOT / record["path"]).read_bytes(), "html.parser")
                    for img in soup.select(".entry img[src]"):
                        references.add(image_family(img["src"]))
        values.sort(key=lambda r: (image_family(r["original"]) not in references, r["original"]))
    return values


def fetch(row):
    source = row.get("source") or f'https://web.archive.org/web/{row["timestamp"]}id_/{row["original"]}'
    record = {**row, "source": source, "retrieved_at": datetime.now(timezone.utc).isoformat()}
    try:
        try:
            body, info = curl_with_info(source)
        except RuntimeError as exc:
            if row["kind"] == "image" and "web.archive.org/web/" in source and "id_/" in source and "error: 404" in str(exc):
                # Some CDX-listed images fail raw replay but work in image mode.
                body, info = curl_with_info(source.replace("id_/", "im_/", 1))
            else:
                raise
        effective = info.get("url_effective", source)
        if urlsplit(effective).hostname not in {"web.archive.org", "arquivo.pt"}:
            raise ValueError("Replay redirected outside the archive")
        capture = re.search(r"/web/(\d{14})", effective)
        if capture and capture[1][:4] > "2016":
            # A later capture of an unchanged external CDN URL can still hold
            # the original cover/photo. Never allow later reuse of blimpyb.com.
            if not (row["kind"] == "image" and row.get("allow_later_capture")
                    and url_key(effective) == url_key(row["original"])
                    and urlsplit(row["original"]).hostname not in {"blimpyb.com", "www.blimpyb.com"}):
                raise ValueError("Replay redirected outside the historic date range")
            record["later_capture"] = True
        record.update(requested_source=source, source=effective, http_status=info.get("http_code"))
        digest = hashlib.sha256(body).hexdigest()
        if row["kind"] == "image":
            with Image.open(io.BytesIO(body)) as image:
                width, height = image.size
                extension = {"JPEG": ".jpg", "PNG": ".png", "GIF": ".gif", "WEBP": ".webp"}[image.format]
                image.verify()
            with Image.open(io.BytesIO(body)) as image:
                image.load()  # JPEG verify() alone does not decode the pixel stream.
            record.update(width=width, height=height)
            path = ARCHIVE / "assets" / (digest[:20] + extension)
        elif row["kind"] == "feed":
            root = ET.fromstring(body)
            if root.tag not in {"rss", "{http://www.w3.org/2005/Atom}feed"}:
                raise ValueError("Response is not an RSS/Atom feed")
            path = ARCHIVE / "raw" / (hashlib.sha256(record_key(row).encode()).hexdigest()[:20] + ".xml")
        else:
            soup = BeautifulSoup(body, "html.parser")
            if not soup.select_one(".entry, .boxpost, .post"):
                raise ValueError("Response has no historic blog content; not imported")
            aid = article_id(row["original"])
            if aid and not soup.select_one(f"#post-{aid} .entry"):
                raise ValueError("Replay did not contain the requested article ID")
            path = ARCHIVE / "raw" / (hashlib.sha256(url_key(row["original"]).encode()).hexdigest()[:20] + ".html")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        record.update(status="ok", path=path.relative_to(ROOT).as_posix(), sha256=digest, bytes=len(body))
    except Exception as exc:
        record.update(status="failed", error=str(exc))
    time.sleep(0.3)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["index", "pages", "images", "arquivo", "linked-pages", "feeds", "external-images"])
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--delay", type=float, default=5.0, help="Minimum seconds between requests")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    global REQUEST_DELAY
    REQUEST_DELAY = max(5, args.delay)
    if args.phase == "index":
        (ARCHIVE / "indexes").mkdir(parents=True, exist_ok=True)
        indexes = {"wayback": CDX_URL}
        for name, url, filters in [
            ("wayback-feed-captures", "blimpyb.com/feed/", ["statuscode:200"]),
            ("wayback-category-feed-captures", "blimpyb.com/category/*", ["statuscode:200", "urlkey:.*feed.*"]),
        ]:
            indexes[name] = "https://web.archive.org/cdx/search/cdx?" + urlencode({
                "url": url, "output": "json", "filter": filters,
                "collapse": "digest", "to": "2016",
            }, doseq=True)
        for name, url in indexes.items():
            body = curl(url)
            rows = json.loads(body)
            if not rows or rows[0][0] != "urlkey":
                raise ValueError("Invalid CDX response")
            (ARCHIVE / "indexes" / f"{name}.json").write_bytes(body)
            save_json(ARCHIVE / "indexes" / f"{name}-source.json", {
                "url": url, "retrieved_at": datetime.now(timezone.utc).isoformat(), "records": len(rows)-1,
            })
            print(f"Indexed {len(rows)-1} records: {name}", flush=True)
        return
    manifest_name = {"arquivo": "images", "external-images": "images", "linked-pages": "pages"}.get(args.phase, args.phase)
    manifest_path = ARCHIVE / f'{manifest_name}.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    if args.phase == "arquivo":
        rows = [json.loads(line) for line in (ARCHIVE / "indexes/arquivo-cdx-response.json").read_text().splitlines() if line.strip()]
        selected = {url_key(r["url"]): dict(original=r["url"], timestamp=r["timestamp"], kind="image", provider="Arquivo.pt / InternetMemory", source=f'https://arquivo.pt/wayback/{r["timestamp"]}id_/{r["url"]}') for r in rows if r["mime"].startswith("image/")}
        selected = list(selected.values())
    elif args.phase == "linked-pages":
        from discover import discover
        selected = [{**r, "kind": "page"} for r in discover()["articles"]]
    elif args.phase == "feeds":
        rows = json.loads((ARCHIVE / "indexes/wayback-feed-captures.json").read_text())
        rows = [dict(zip(rows[0], r)) for r in rows[1:]]
        additional = ARCHIVE / "indexes/wayback-category-feed-captures.json"
        if additional.exists():
            captures = json.loads(additional.read_text())
            rows += [dict(zip(captures[0], r)) for r in captures[1:]]
        rows += [r for r in inventory() if re.fullmatch(r"/category/[^/]+/feed/|/feed/atom/", urlsplit(r["original"]).path)]
        selected = [{**r, "original": original_url(r["original"]), "kind": "feed"} for r in rows]
        selected = list({record_key(r): r for r in selected}.values())
    elif args.phase == "external-images":
        from build import load_documents
        selected = {}
        for record in load_documents():
            if record["kind"] != "article":
                continue
            capture = re.search(r"/web/(\d{14})", record["source"])
            if not capture:
                continue
            soup = BeautifulSoup(record["html"], "html.parser")
            for img in soup.select("img[src]"):
                url = original_url(urljoin(record["original"], img["src"]))
                p = urlsplit(url)
                if p.scheme not in {"http", "https"} or not p.hostname:
                    continue
                if any(host in p.hostname for host in ["blimpyb.com", "shareasale.com", "linksynergy.com", "doubleclick.net", "googlesyndication.com"]):
                    continue
                if img.get("width") == "1" and img.get("height") == "1":
                    continue
                selected[url_key(url)] = dict(original=url, timestamp=capture[1], kind="image",
                                             discovered_in=record["source"], allow_later_capture=True)
        selected = list(selected.values())
    else:
        selected = targets(inventory(), args.phase)
    pending = []
    for row in selected:
        old = manifest.get(record_key(row))
        if old and old["status"] == "ok" and (ROOT / old["path"]).is_file():
            continue
        if old and old["status"] == "failed" and not args.retry_failed:
            continue
        pending.append(row)
    if args.limit:
        pending = pending[:args.limit]
    print(f"Fetching {len(pending)} {args.phase}; successful downloads will be reused", flush=True)
    pool = ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4)))
    consecutive_outages = 0
    try:
        jobs = [pool.submit(fetch, row) for row in pending]
        for i, job in enumerate(as_completed(jobs), 1):
            record = job.result()
            manifest[record_key(record)] = record
            save_json(manifest_path, manifest)
            print(f'{i}/{len(jobs)} {record["status"]}: {record["original"]}', flush=True)
            error = record.get("error", "")
            is_outage = any(marker in error for marker in ["curl: (7)", "curl: (28)", "error: 429", "error: 503"])
            consecutive_outages = consecutive_outages + 1 if is_outage else 0
            if consecutive_outages >= 3:
                raise SystemExit("Archive repeatedly unavailable. Progress is saved; retry later.")
    except KeyboardInterrupt:
        for job in jobs:
            job.cancel()
        print("Stopped. Completed downloads are saved; run again to resume.", flush=True)
        raise SystemExit(130)
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    print(f'{sum(r["status"] == "ok" for r in manifest.values())} successful; {sum(r["status"] == "failed" for r in manifest.values())} failed')


if __name__ == "__main__":
    main()
