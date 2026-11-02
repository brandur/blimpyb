#!/usr/bin/env python3
"""Find additional article and image leads in saved HTML, without networking."""
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from recover import ROOT, ARCHIVE, article_id, image_family, inventory, original_url, save_json, url_key


def discover():
    indexed_ids = {article_id(r["original"]) for r in inventory() if article_id(r["original"])}
    indexed_images = {image_family(r["original"]) for r in inventory() if r["mimetype"].startswith("image/")}
    pages = json.loads((ARCHIVE / "pages.json").read_text())
    article_leads, image_leads = {}, {}
    for record in pages.values():
        if record["status"] != "ok":
            continue
        soup = BeautifulSoup((ROOT / record["path"]).read_bytes(), "html.parser")
        for a in soup.select("a[href]"):
            url = original_url(urljoin(record["original"], a["href"])).split("#")[0]
            aid = article_id(url)
            if aid and aid not in indexed_ids:
                old = article_leads.get(aid)
                title = a.get_text(" ", strip=True)
                if not old or (len(title) > len(old["title"]) and title != "ADD COMMENTS"):
                    article_leads[aid] = dict(id=aid, original=url, title=title, discovered_in=record["source"], timestamp=record["timestamp"])
        for image in soup.select(".entry img[src]"):
            url = original_url(urljoin(record["original"], image["src"]))
            if urlsplit(url).hostname not in {"blimpyb.com", "www.blimpyb.com"} or "/uploads/" not in url or "wpcf7_captcha" in url:
                continue
            family = image_family(url)
            if family not in indexed_images:
                image_leads[family] = dict(original=url, alt=image.get("alt") or image.get("title", ""), discovered_in=record["source"], timestamp=record["timestamp"])
    map_path = ARCHIVE / "map-locations.json"
    if map_path.exists():
        source = json.loads((ARCHIVE / "map.json").read_text())["source"]
        timestamp = re.search(r"/web/(\d{14})", source)[1]
        for point in json.loads(map_path.read_text())["objects"]:
            aid = point["object_id"]
            if point["categories"] and aid not in indexed_ids and aid not in article_leads:
                article_leads[aid] = dict(id=aid, original=f"http://blimpyb.com/?p={aid}", title=point["title"], discovered_in=source, timestamp=timestamp)
    report = dict(articles=list(article_leads.values()), images=list(image_leads.values()))
    save_json(ARCHIVE / "leads.json", report)
    print(f'Found {len(article_leads)} article IDs and {len(image_leads)} image families outside the saved Wayback index')
    return report


if __name__ == "__main__":
    discover()
