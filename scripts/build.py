#!/usr/bin/env python3
"""Build a completely offline static reader from preserved source material."""
import argparse
from collections import defaultdict
from datetime import datetime
from email.utils import parsedate_to_datetime
import hashlib
from html import escape, unescape
import json
from pathlib import Path
import re
import shutil
import tomllib
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup, Comment
import markdown
from PIL import Image

from recover import ROOT, ARCHIVE, article_id, image_family, original_url, url_key, save_json

DIST = ROOT / "dist"


def read_manifest(name):
    path = ARCHIVE / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else {}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "article"


def archived(url, timestamp="2014"):
    if "web.archive.org/web/" in url:
        return url
    return f"https://web.archive.org/web/{timestamp}/{url}"


def feed_documents(body, record):
    """Use full RSS/Atom content; descriptions and summaries may be excerpts."""
    root = ET.fromstring(body)
    docs = []
    atom = "{http://www.w3.org/2005/Atom}"
    for item in root.findall(atom + "entry"):
        link = item.find(atom + "link[@rel='alternate']")
        content = item.find(atom + "content[@type='html']")
        url = original_url(link.get("href", "")) if link is not None else ""
        aid = article_id(url)
        title = item.findtext(atom + "title", "")
        date = item.findtext(atom + "published", "")
        if not (aid and content is not None and content.text and title and date):
            continue
        docs.append(dict(id=aid, title=unescape(title), date=datetime.fromisoformat(date).date().isoformat(),
                         original=url, source=record["source"], html=content.text, kind="article",
                         categories=[c.get("term") for c in item.findall(atom + "category") if c.get("term")],
                         origin="archived Atom full content", raw_path=record["path"]))
    for item in root.findall("./channel/item"):
        url = original_url(item.findtext("link", ""))
        aid = article_id(url)
        content = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", "")
        title = item.findtext("title", "")
        date = item.findtext("pubDate", "")
        if not (aid and content.strip() and title and date):
            continue
        docs.append(dict(id=aid, title=unescape(title), date=parsedate_to_datetime(date).date().isoformat(),
                         original=url, source=record["source"], html=content, kind="article",
                         categories=[c.text for c in item.findall("category") if c.text],
                         origin="archived RSS full content", raw_path=record["path"]))
    return docs


def load_documents():
    docs = {}
    for path in sorted((ROOT / "content/articles").glob("*.md")):
        _, front, body = path.read_text().split("+++", 2)
        meta = tomllib.loads(front)
        url = original_url(meta["wayback_machine_url"])
        aid = article_id(url)
        body = re.sub(r"^\s*# [^\n]+\n", "", body, count=1)
        docs[aid] = dict(id=aid, title=meta["title"], date=meta["published_at"][:10],
                         original=url, source=meta["wayback_machine_url"],
                         html=markdown.markdown(body, extensions=["extra"]),
                         kind="article", categories=[], origin="original Markdown", raw_path=str(path.relative_to(ROOT)))
    for record in sorted(read_manifest("pages").values(), key=lambda r: r.get("timestamp", "")):
        if record["status"] != "ok":
            continue
        url = record["original"]
        path = urlsplit(url).path
        aid = article_id(url)
        kind = "article" if aid else "gallery" if re.fullmatch(r"/gallery/[^/]+/", path) else "page"
        if not aid and kind != "gallery" and path != "/about/":
            continue
        soup = BeautifulSoup((ROOT / record["path"]).read_bytes(), "html.parser")
        post = soup.select_one(f"#post-{aid}") if aid else soup.select_one(".post")
        if not post or not post.select_one(".entry"):
            continue
        title = post.select_one(".title h2, h2, h1")
        if not title:
            continue
        date = ""
        clock = post.select_one(".clock")
        if clock:
            match = re.search(r"([A-Za-z]+)\s*-\s*(\d+)\s*-\s*(\d{4})", clock.get_text())
            if match:
                date = datetime.strptime(" ".join(match.groups()), "%B %d %Y").date().isoformat()
        if kind == "article" and not date:
            # An archive/category excerpt is never silently promoted to a full article.
            continue
        key = aid or path
        docs[key] = dict(id=key, title=title.get_text(" ", strip=True), date=date,
                         original=url, source=record["source"], html=str(post.select_one(".entry")),
                         kind=kind, categories=[a.get_text(strip=True) for a in post.select(".categoryb a")],
                         origin="Wayback HTML", raw_path=record["path"])
    known_categories = {category for doc in docs.values() for category in doc["categories"]}
    for record in sorted(read_manifest("feeds").values(), key=lambda r: r["timestamp"], reverse=True):
        if record["status"] == "ok":
            for doc in feed_documents((ROOT / record["path"]).read_bytes(), record):
                # WordPress RSS mixes tags and categories in the same XML field.
                if known_categories:
                    doc["tags"] = [c for c in doc["categories"] if c not in known_categories]
                    doc["categories"] = [c for c in doc["categories"] if c in known_categories]
                docs.setdefault(doc["id"], doc)
    for doc in docs.values():
        folder = {"article": "articles", "gallery": "galleries", "page": "pages"}[doc["kind"]]
        stem = f'{doc["date"]}-' if doc["date"] else ""
        doc["path"] = f'{folder}/{stem}{slug(doc["title"])}.html'
    return sorted(docs.values(), key=lambda d: (d["date"], d["title"]), reverse=True)


def unrecovered_articles(docs):
    path = ARCHIVE / "leads.json"
    if not path.exists():
        return []
    recovered_ids = {d["id"] for d in docs}
    missing = {r["id"]: dict(r) for r in json.loads(path.read_text())["articles"] if r["id"] not in recovered_ids}
    for record in read_manifest("pages").values():
        if record["status"] != "ok":
            continue
        soup = BeautifulSoup((ROOT / record["path"]).read_bytes(), "html.parser")
        for post in soup.select(".post[id]"):
            aid = post["id"].removeprefix("post-")
            entry = post.select_one(".entry")
            if aid not in missing or not entry:
                continue
            text = entry.get_text(" ", strip=True)
            if len(text) > len(missing[aid].get("excerpt", "")):
                title = post.select_one(".title h2")
                if title:
                    missing[aid]["title"] = title.get_text(" ", strip=True)
                missing[aid].update(excerpt=text, excerpt_source=record["source"])
    return list(missing.values())


def collect_tags(docs):
    """Index explicit tag metadata, including tags preserved only in feeds."""
    tags, names = {}, {}
    for doc in docs:
        doc["tag_keys"] = []
        soup = BeautifulSoup(doc["html"], "html.parser")
        for link in soup.select("a[rel~=tag][href]"):
            url = original_url(urljoin(doc["original"], link["href"]))
            parsed = urlsplit(url)
            match = re.fullmatch(r"/tag/([^/]+)/?", parsed.path)
            if parsed.hostname not in {"blimpyb.com", "www.blimpyb.com"} or not match:
                continue
            key = "tag:" + unquote(match[1]).casefold()
            name = link.get_text(" ", strip=True) or unquote(match[1])
            tag = tags.setdefault(key, dict(name=name, documents=[], urls=set()))
            tag["urls"].add(url_key(url))
            names.setdefault(name.casefold(), key)
            if key not in doc["tag_keys"]:
                doc["tag_keys"].append(key)
                tag["documents"].append(doc)
    for doc in docs:
        doc["extra_tag_keys"] = []
        for name in doc.get("tags", []):
            key = names.setdefault(name.casefold(), "feed:" + name.casefold())
            tag = tags.setdefault(key, dict(name=name, documents=[], urls=set()))
            if key not in doc["tag_keys"]:
                doc["tag_keys"].append(key)
                doc["extra_tag_keys"].append(key)
                tag["documents"].append(doc)
    filenames = defaultdict(list)
    for key, tag in tags.items():
        filenames[slug(key[4:] if key.startswith("tag:") else tag["name"])].append(key)
    links = {}
    for filename, keys in filenames.items():
        for key in keys:
            suffix = "-" + hashlib.sha256(key.encode()).hexdigest()[:8] if len(keys) > 1 else ""
            tags[key]["path"] = f"tags/{filename}{suffix}.html"
            links.update({url: tags[key]["path"] for url in tags[key]["urls"]})
    return tags, links


class Assets:
    def __init__(self):
        self.families = defaultdict(list)
        self.legacy = {}
        self.invalid = []
        for record in read_manifest("images").values():
            if record["status"] == "ok" and (ROOT / record["path"]).exists():
                self.families[image_family(record["original"])].append(record)
        for path in sorted((ROOT / "content/images").glob("*/*")):
            try:
                with Image.open(path) as img:
                    width, height = img.size
                    img.verify()
                with Image.open(path) as img:
                    img.load()
                rec = dict(path=str(path.relative_to(ROOT)), width=width, height=height,
                           sha256=hashlib.sha256(path.read_bytes()).hexdigest(), original="")
                self.legacy["../images/" + str(path.relative_to(ROOT / "content/images"))] = rec
                # Old files are stored per article; recover their upload month from raw references.
                # Never match a common camera filename globally across unrelated uploads.
            except Exception as exc:
                self.invalid.append({"path": str(path.relative_to(ROOT)), "reason": type(exc).__name__})
        self.copied = {}

    def find(self, url, doc=None):
        if url in self.legacy:
            return self.legacy[url]
        matches = self.families.get(image_family(url), [])
        if matches:
            return max(matches, key=lambda r: r["width"] * r["height"])
        if doc:
            # Limit fallback matching to the original article's own image directory.
            aid = article_id(doc["original"])
            for source in (ROOT / "content/articles").glob("*.md"):
                text = source.read_text()
                meta = tomllib.loads(text.split("+++", 2)[1])
                if article_id(meta["wayback_machine_url"]) != aid:
                    continue
                wanted = image_family(url).rsplit("/", 1)[-1]
                for key, record in self.legacy.items():
                    if f"/{source.stem}/" in key and image_family(key).rsplit("/", 1)[-1] == wanted:
                        return record
        return None

    def local(self, record):
        source = ROOT / record["path"]
        name = record["sha256"][:20] + source.suffix.lower()
        target = DIST / "images" / name
        if name not in self.copied:
            shutil.copyfile(source, target)
            self.copied[name] = record
        return "../images/" + name


def prepare_content(doc, assets, links, ids):
    soup = BeautifulSoup(doc["html"], "html.parser")
    missing, recovered = [], []
    for element in soup.select("script, style, link, meta, form, input, button, textarea, .akpc_pop, .widebanner, .sharedaddy, [class^='shr-']"):
        element.decompose()
    for element in soup.find_all(string=lambda t: isinstance(t, Comment)):
        element.extract()
    for element in soup.select('img[src*="shareasale.com"], img[src*="doubleclick.net"], img[src*="googlesyndication.com"], img[src*="ad.linksynergy.com"], img[src*="ak_action=api_record_view"], img[width="1"][height="1"]'):
        element.decompose()
    for element in soup.select(".gallery > br"):
        element.decompose()  # Old float-clearing breaks would create empty grid cells.
    for item in soup.select(".gallery-item"):
        item.name = "figure"
        icon = item.select_one(".gallery-icon")
        if icon:
            icon.name = "div"
        image = item.find("img")
        if image and not item.select_one(".gallery-caption, figcaption"):
            caption_text = image.get("title") or image.get("alt")
            if caption_text:
                caption = soup.new_tag("figcaption")
                caption.string = caption_text
                item.append(caption)
    for element in soup.select("iframe, object, embed"):
        if element.attrs is None:  # Its enclosing object may already be removed.
            continue
        source = element.get("src") or element.get("data")
        if not source:
            param = element.select_one('param[name="movie"]')
            source = param.get("value") if param else None
        if source and any(site in source for site in ["youtube.com", "youtu.be", "vimeo.com"]):
            video_url = original_url(source)
            youtube = re.search(r"youtube\.com/(?:v|embed)/([^?&/]+)", video_url)
            if youtube:
                video_url = "https://www.youtube.com/watch?v=" + youtube[1]
            vimeo = re.search(r"player\.vimeo\.com/video/(\d+)", video_url)
            if vimeo:
                video_url = "https://vimeo.com/" + vimeo[1]
            link = soup.new_tag("a", href=video_url)
            link.string = "Watch the original video (requires internet)"
            element.replace_with(link)
        else:
            element.decompose()
    for image in list(soup.find_all("img")):
        src = image.get("src", "")
        url = original_url(urljoin(doc["original"], src))
        alt = image.get("alt") or image.get("title") or "Archived photograph"
        parent = image.find_parent("a")
        full = assets.find(original_url(urljoin(doc["original"], parent.get("href", ""))), doc) if parent else None
        record = assets.find(src, doc) or assets.find(url, doc) or full
        if record:
            image.attrs = dict(src=assets.local(record), alt=alt, width=str(record["width"]), height=str(record["height"]), loading="lazy", decoding="async")
            recovered.append({"original": url, "matched_original": record.get("original") or None,
                              "source": record.get("source"), "file": record["path"],
                              "reader_file": assets.local(record).removeprefix("../"),
                              "width": record["width"], "height": record["height"]})
            if parent:
                parent["href"] = assets.local(full or record)
        else:
            placeholder = soup.new_tag("span", attrs={"class": "missing-photo", "role": "img", "aria-label": alt + " (unrecovered)"})
            figure = image.find_parent("figure")
            caption = figure.find("figcaption") if figure else None
            placeholder.string = "Image not recovered" if caption and caption.get_text(strip=True) == alt else "Image not recovered · " + alt
            image.replace_with(placeholder)
            missing.append({"original": None if src.startswith("../images/") else url, "alt": alt})
    for p in soup.find_all("p"):
        if "(missing image)" in p.get_text():
            p["class"] = "missing-photo"
            missing.append({"original": None, "alt": p.get_text(" ", strip=True)})
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("../images/"):
            if not (DIST / "articles" / href).is_file():
                a.unwrap()
            continue
        if href.startswith("#"):
            continue
        url = original_url(urljoin(doc["original"], href))
        target = links.get(url_key(url)) or ids.get(article_id(url))
        asset = assets.find(url, doc)
        if target:
            a["href"] = "../" + target
        elif asset:
            a["href"] = assets.local(asset)
        elif urlsplit(url).hostname in {"blimpyb.com", "www.blimpyb.com"}:
            a["href"] = archived(url)
            a["title"] = "Not recovered locally; opens the Internet Archive"
        elif urlsplit(url).scheme in {"http", "https", "mailto"}:
            a["href"] = href if "web.archive.org/web/" in href else url
        else:
            del a["href"]
    for figure in soup.select(".wp-caption"):
        figure.name = "figure"
    for caption in soup.select(".wp-caption-text, .gallery-caption"):
        caption.name = "figcaption"
    allowed = {"a", "p", "div", "span", "br", "hr", "blockquote", "strong", "b", "em", "i", "u", "s", "del", "sub", "sup", "h2", "h3", "h4", "h5", "ul", "ol", "li", "dl", "dt", "dd", "figure", "figcaption", "img", "table", "thead", "tbody", "tr", "th", "td", "pre", "code"}
    for tag in list(soup.find_all(True)):
        if tag.name not in allowed:
            tag.unwrap()
            continue
        permitted = {"href", "title"} if tag.name == "a" else {"src", "alt", "width", "height", "loading", "decoding"} if tag.name == "img" else {"colspan", "rowspan"} if tag.name in {"td", "th"} else set()
        classes = set(tag.get("class", [])) if isinstance(tag.get("class"), list) else {tag.get("class", "")}
        keep_class = "missing-photo" if "missing-photo" in classes else "gallery-grid" if "gallery" in classes else "gallery-item" if "gallery-item" in classes else None
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in permitted}
        if keep_class:
            tag["class"] = keep_class
    for tag in reversed(list(soup.find_all(["div", "span", "p"]))):
        if not tag.get_text(strip=True) and not tag.find(["img", "hr", "br"]):
            tag.decompose()
    doc.update(body=str(soup), missing=missing, recovered=recovered, text=soup.get_text(" ", strip=True))


def layout(title, body, depth=0):
    prefix = "../" * depth
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light"><title>{escape(title)} · BlimpyB archive</title>
<link rel="stylesheet" href="{prefix}style.css"><script src="{prefix}reader.js" defer></script></head>
<body><a class="skip" href="#main">Skip to content</a>
<header class="masthead"><a class="brand" href="{prefix}index.html">Blimpy<span>B</span><small>THE ARCHIVE</small></a>
<nav aria-label="Main"><a href="{prefix}index.html">Articles</a><a href="{prefix}galleries.html">Photographs</a><a href="{prefix}recovery.html">About this archive</a></nav></header>
{body}<footer><span>Blimpy Backgammon · Words &amp; photographs from the road</span><a href="{prefix}recovery.html">Preservation notes</a></footer></body></html>'''


def pretty_date(date):
    return datetime.fromisoformat(date).strftime("%B %-d, %Y") if date else ""


def build():
    # dist/ is wholly generated; discard obsolete slugs and old asset selections.
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(exist_ok=True)
    for directory in ["articles", "galleries", "pages", "images", "tags"]:
        (DIST / directory).mkdir(exist_ok=True)
    for filename in ["style.css", "reader.js"]:
        shutil.copyfile(ROOT / "web" / filename, DIST / filename)
    docs = load_documents()
    incomplete = unrecovered_articles(docs)
    assets = Assets()
    links = {url_key(d["original"]): d["path"] for d in docs}
    links.update({url_key("http://blimpyb.com/"): "index.html", url_key("http://blimpyb.com/gallery/"): "galleries.html"})
    tags, tag_links = collect_tags(docs)
    links.update(tag_links)
    ids = {article_id(d["original"]): d["path"] for d in docs if article_id(d["original"])}
    articles = [d for d in docs if d["kind"] == "article"]
    galleries = [d for d in docs if d["kind"] == "gallery"]
    for doc in docs:
        prepare_content(doc, assets, links, ids)
        if doc["extra_tag_keys"]:
            tag_labels = [f'<a href="../{tags[key]["path"]}">{escape(tags[key]["name"])}</a>' for key in doc["extra_tag_keys"]]
            doc["body"] += '<p>Tags: ' + ' | '.join(tag_labels) + '</p>'
            doc["text"] += ' Tags: ' + ' | '.join(tags[key]["name"] for key in doc["extra_tag_keys"])
        adjacent = ""
        if doc in articles:
            i = articles.index(doc)
            adjacent = '<nav class="adjacent" aria-label="Adjacent articles">'
            if i + 1 < len(articles):
                d = articles[i + 1]
                adjacent += f'<a href="../{d["path"]}"><small>← OLDER ARTICLE</small>{escape(d["title"])}</a>'
            if i > 0:
                d = articles[i - 1]
                adjacent += f'<a href="../{d["path"]}"><small>NEWER ARTICLE →</small>{escape(d["title"])}</a>'
            adjacent += '</nav>'
        info = f'{len(doc["recovered"])} images available'
        if doc["missing"]:
            info += f' · {len(doc["missing"])} images not recovered'
        byline = "By Blimpy" + (" · " + " / ".join(doc["categories"]) if doc["categories"] else "")
        gallery_control = '<label class="gallery-toggle"><input id="show-gaps" type="checkbox" checked> Show gaps in the gallery</label>' if doc["kind"] == "gallery" and doc["missing"] and doc["recovered"] else ''
        body = f'''<main id="main" class="reading"><a class="back" href="../{"galleries" if doc["kind"] == "gallery" else "index"}.html">← Back to {"photographs" if doc["kind"] == "gallery" else "articles"}</a>
<header class="article-heading"><p class="eyebrow">{escape(pretty_date(doc["date"]) or doc["kind"])}</p><h1>{escape(doc["title"])}</h1><p class="byline">{escape(byline)}</p></header>
{gallery_control}<div class="prose">{doc["body"]}</div>
<details class="source"><summary>Archive details · {info}</summary><p>Preserved from {escape(doc["origin"])}. <a href="{escape(doc["source"], quote=True)}">View the source capture ↗</a></p><p>Unrecovered images retain their original descriptions where available. A surviving smaller version may be used.</p></details>{adjacent}</main>'''
        (DIST / doc["path"]).write_text(layout(doc["title"], body, 1))
    for tag in tags.values():
        entries = []
        for doc in tag["documents"]:
            label = pretty_date(doc["date"]) or doc["kind"].capitalize()
            entries.append(f'<li><small>{escape(label)}</small><h2><a href="../{doc["path"]}">{escape(doc["title"])}</a></h2></li>')
        count = len(entries)
        body = f'''<main id="main" class="reading"><a class="back" href="../index.html">← Back to articles</a>
<header class="article-heading"><p class="eyebrow">TAGGED IN THE ARCHIVE</p><h1>{escape(tag["name"])}</h1><p class="byline">{count} recovered page{"s" if count != 1 else ""} · Articles and galleries with this tag</p></header>
<ul class="tag-articles">{''.join(entries)}</ul></main>'''
        (DIST / tag["path"]).write_text(layout("Tag: " + tag["name"], body, 1))
    years = sorted({d["date"][:4] for d in articles}, reverse=True)
    categories = sorted({c for d in articles for c in d["categories"]})
    options = lambda values: ''.join(f'<option value="{escape(v, quote=True)}">{escape(v)}</option>' for v in values)
    rows = []
    for doc in articles:
        teaser = re.sub(r"\s+", " ", doc["text"])[:190].rsplit(" ", 1)[0] + "…"
        thumb = ""
        if doc["recovered"]:
            img = BeautifulSoup(doc["body"], "html.parser").find("img")
            thumb = f'<img class="teaser-photo" src="{img["src"].removeprefix("../")}" alt="" loading="lazy">'
        rows.append(f'''<li class="article-row" data-year="{doc["date"][:4]}" data-date="{doc["date"]}" data-categories="{escape(json.dumps(doc["categories"]), quote=True)}" data-search="{escape((doc["title"] + " " + doc["text"]).lower(), quote=True)}">
<time datetime="{doc["date"]}">{escape(pretty_date(doc["date"]))}</time><div><h2><a href="{doc["path"]}">{escape(doc["title"])}</a></h2><p>{escape(teaser)}</p><small>{len(doc["recovered"])} photographs · {escape(" / ".join(doc["categories"][:2]))}</small></div>{thumb}</li>''')
    hero = next((d for preferred in ["quartzsite-az", "westport-and-the-docks-of-the-damned"] for d in articles
                 if preferred in d["original"] and d["recovered"]), next((d for d in articles if d["recovered"]), None))
    photograph = ""
    if hero:
        img = BeautifulSoup(hero["body"], "html.parser").find("img")
        photograph = f'<figure class="hero-photo"><a href="{hero["path"]}"><img src="{img["src"].removeprefix("../")}" alt="{escape(img.get("alt", ""), quote=True)}"></a><figcaption>{escape(hero["title"])}</figcaption></figure>'
    body = f'''<main id="main"><section class="intro"><div><p class="eyebrow">A JOURNAL FROM THE OPEN ROAD · {years[-1]}–{years[0]}</p><h1>Quit job. Buy RV.<br>Kick North America’s ass.</h1><p class="intro-copy">The travels, photographs, experiments, and stories of Blimpy Backgammon. Saved from the old web, for another trip down the road.</p><p class="archive-count">{len(articles)} articles <span> / </span> {len(galleries)} galleries</p></div>{photograph}</section>
<section class="archive-list" aria-labelledby="index-title"><div class="section-line"><h2 id="index-title">The articles</h2><p id="result-count" aria-live="polite">{len(articles)} articles</p></div>
<form class="filters" role="search" onsubmit="return false"><label>Search the archive<input type="search" id="search" placeholder="A place, a story, a few words…"></label><label>Year<select id="year"><option value="">All years</option>{options(years)}</select></label><label>Subject<select id="category"><option value="">All subjects</option>{options(categories)}</select></label><label>Order<select id="sort"><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label></form>
<ul id="articles">{''.join(rows)}</ul><p id="empty" hidden>No articles match. Try a different word, year, or subject.</p><noscript><p>All articles are listed below. Search and filters require JavaScript.</p></noscript></section></main>'''
    (DIST / "index.html").write_text(layout("Articles", body))
    cards = []
    for d in galleries:
        img = BeautifulSoup(d["body"], "html.parser").find("img")
        photo = f'<img src="{img["src"].removeprefix("../")}" alt="" loading="lazy">' if img else '<div class="missing-photo">Photographs not yet recovered</div>'
        cards.append(f'<a class="gallery-card" href="{d["path"]}">{photo}<h2>{escape(d["title"])}</h2><p>{len(d["recovered"])} available · {len(d["missing"])} unrecovered</p></a>')
    # Preserve access to images whose parent article/gallery was not captured.
    all_photos = []
    for family, records in sorted(assets.families.items()):
        if "/uploads/" not in family:
            continue
        rec = max(records, key=lambda r: r["width"] * r["height"])
        local = assets.local(rec).removeprefix("../")
        name = unquote(family.rsplit("/", 1)[-1])
        all_photos.append(f'<figure><a href="{local}"><img src="{local}" alt="{escape(name, quote=True)}" loading="lazy" width="{rec["width"]}" height="{rec["height"]}"></a><figcaption><a href="{escape(rec["source"], quote=True)}">{escape(name)}</a> · {rec["width"]} × {rec["height"]}</figcaption></figure>')
    (DIST / "galleries.html").write_text(layout("Photographs", f'<main id="main"><section class="page-heading"><p class="eyebrow">THROUGH THE WINDSHIELD</p><h1>Photographs from the road</h1><p>Original galleries and every recovered upload, including photographs whose pages are still missing.</p></section><div class="gallery-cards">{"".join(cards)}</div><h2>All recovered uploads</h2><div class="photo-library">{"".join(all_photos)}</div></main>'))
    report = {"articles": len(articles), "galleries": len(galleries), "tag_pages": len(tags), "local_image_files": len(assets.copied),
              "image_families": len(all_photos), "invalid_legacy_images": assets.invalid,
              "unrecovered_articles": incomplete,
              "documents": [{k: d[k] for k in ["title", "date", "path", "original", "source", "origin", "raw_path", "missing", "recovered"]} for d in docs]}
    save_json(DIST / "recovery.json", report)
    missing_count = sum(len(d["missing"]) for d in docs)
    missing_rows = ''.join(f'<li><a href="{d["path"]}">{escape(d["title"])}</a> · {len(d["missing"])} image references unrecovered</li>' for d in docs if d["missing"])
    incomplete_rows = ''.join(f'<li><a href="{escape(archived(d["original"]), quote=True)}">{escape(d["title"])}</a>' + (f'<p class="excerpt-label">Surviving excerpt · <a href="{escape(d["excerpt_source"], quote=True)}">source</a></p><blockquote>{escape(d["excerpt"])}</blockquote>' if d.get("excerpt") else '') + '</li>' for d in incomplete)
    incomplete_section = f'<h2>Articles still missing</h2><p>{len(incomplete)} other article titles appear in the saved pages, but their complete bodies have not been recovered. Any surviving excerpts are shown below and are not counted as full articles.</p><ul>{incomplete_rows}</ul>' if incomplete else ''
    about = next((d for d in docs if d["original"].endswith("/about/")), None)
    about_link = f'<p><a href="{about["path"]}">Read Blimpy’s original introduction →</a></p>' if about else ""
    body = f'''<main id="main" class="reading"><p class="eyebrow">PRESERVATION NOTES</p><h1>About this archive</h1><div class="prose"><p>This is a local reading copy of Blimpy Backgammon’s former website, blimpyb.com. The author’s words and captions are preserved; the layout has been rebuilt for reading.</p>{about_link}<p>The archive currently contains <strong>{len(articles)} articles, {len(galleries)} galleries, and {len(assets.copied)} image files</strong>. Internet Archive and Arquivo.pt captures provide the recovered material. The original 28 Markdown articles remain preserved in the repository.</p><p>Some photographs survive only as thumbnails or resized copies. The reader uses the largest verified copy found for the same original upload. Missing images are marked in place; no replacement photographs have been invented.</p><p>All article text, styles, navigation, search, and available images work offline. Source links, unrecovered destinations, and video links require internet access. Historic scripts, adverts, forms, and trackers are omitted.</p><p>Two files in the old mirror had .jpg filenames but contained empty HTML responses; they are retained as original evidence and are not served as images.</p><p>Each article links to its source capture. <a href="recovery.json">Download the recovery inventory</a> for original URLs, local files, dimensions, and outstanding gaps.</p><h2>Still missing</h2><p>{missing_count} image references across the saved pages remain unrecovered (the same photograph may occur on several pages). An uncaptured page or image may still exist elsewhere.</p><ul>{missing_rows}</ul></div></main>'''
    body = body.replace('<h2>Still missing</h2>', incomplete_section + '<h2>Images still missing</h2>')
    (DIST / "recovery.html").write_text(layout("About this archive", body))
    print(f'Built {len(articles)} articles, {len(galleries)} galleries, {len(tags)} tag pages, {len(assets.copied)} image files → {DIST}')
    return report


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    build()
