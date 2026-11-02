# Maintaining the BlimpyB archive

This is a technical handoff for a future maintainer or coding agent. It records
how the recovery was performed, how the current implementation turns preserved
material into a reader, and where to make changes. The recovery and tag-index
baseline below was checked on **November 2, 2026**. Counts are observations, not
limits to hard-code into the application.

Start with [README.md](README.md) for ordinary usage. For implementation work,
read this guide, then the relevant functions in [scripts/build.py](scripts/build.py)
or [scripts/recover.py](scripts/recover.py). For further recovery, consult
[the investigation log](archive/indexes/investigation.json) before making
network requests.

## 1. Intent and source of truth

The project preserves the writing and photographs of Blimpy Backgammon's former
WordPress site, blimpyb.com. The reader is a new static layout, not a recreation
of the original WordPress installation. It has no database, backend application,
JavaScript framework, or frontend package manager.

There are three distinct layers:

| Layer | Files | How to treat it |
| --- | --- | --- |
| Earlier recovery | `content/articles/`, `content/images/`, `fetch.rb` | Historical evidence and fallback content. The recovery described here left these files unchanged. |
| New preserved evidence | `archive/` | Downloaded bytes, discovery indexes, provenance, and failed attempts. Keep the originals and their hashes intact. |
| Generated reader | `dist/` | Disposable output. `make build` deletes this whole directory and recreates it. Change the generator or `web/`, not these files. |

The new article sources are primarily **HTML**, with additional full bodies in
**RSS/Atom XML**. The old 28 articles remain Markdown with TOML front matter.
There is no separately maintained, normalized Markdown copy of every recovered
article. Normalized document objects exist in memory during a build.

Preservation decisions that should survive future changes:

- Keep original prose, captions, dates, and attribution. Fix extraction or
  rendering in code rather than silently rewriting a downloaded source file.
- Do not invent missing text, substitute unrelated photographs, or present
  excerpts as complete articles. Gaps are useful evidence and are shown openly.
- Keep image matches tied to the same original upload, even when only a small
  variant survives. A repeated camera filename alone is not enough evidence.
- Preserve offline reading and relative links. External citations, videos, and
  source-capture links can require the internet; embedded reader resources do not.
- Serve `dist/`, not the repository root. Raw captures contain obsolete scripts,
  adverts, and forms that the generated reader deliberately removes.

The `.gitattributes` entries disable text conversion for saved payloads. Their
SHA-256 hashes cover the actual bytes, including original line endings.

## 2. Run, build, and inspect

Run commands from the repository root. Python **3.11+** and `make` are required;
network recovery additionally uses a `curl` that supports `--write-out %{json}`.
The current build uses POSIX-style tools and date formatting; Windows-specific
support has not been established.

```sh
# Once per environment; installs the pinned Python dependencies.
make setup

# Build and serve only the generated reader on localhost.
make serve

# If another process already uses port 8000:
make serve PORT=8001

# Rebuild without starting a server.
make build

# Rebuild, run unit tests, and check generated files and preserved hashes.
make check
```

`make setup PYTHON=python3.12` is an example of selecting a suitable interpreter
when the default `python3` is older. Subsequent targets use `.venv/bin/python`.
Python dependencies are pinned in [requirements.txt](requirements.txt).

The default address is `http://127.0.0.1:8000`. Stop an owned preview server with
Ctrl-C when finished. `make serve` builds once; it does **not** watch files or
rebuild after edits. Run `make build` again and refresh the browser.

Opening `dist/index.html` with `file://` also works. Navigation and tag pages need
no JavaScript. Full-text search, year/category/order filters, and the gallery
gap toggle use local JavaScript. Building and reading need no network access
once dependencies and the saved archive are present.

### Pull-request CI

[.github/workflows/ci.yaml](.github/workflows/ci.yaml) runs on pull requests when
they are opened, updated, or reopened. Its **Build and validate** job uses Ubuntu
and Python 3.13, runs `make setup`, then runs `make check`. This rebuilds the site,
runs the unit tests, and verifies generated links, image decoding, and saved
payload hashes. Keep its Python version and build commands aligned with the
Pages workflow below.

The workflow has read-only repository permissions and does not deploy or run
archive recovery. It caches pip downloads and cancels an older run when the same
pull request is updated. A manual `workflow_dispatch` trigger is also available
once the workflow is present on the default branch. The workflow must be pushed
before GitHub can run it; local verification uses the same `make check` target.

### Publishing to GitHub Pages

The public reader's URL is <https://brandur.github.io/blimpyb/>. The repository's
Pages publishing source is configured as **GitHub Actions**. The workflow in
[.github/workflows/pages.yaml](.github/workflows/pages.yaml) runs on pushes to
`master` and can also be started manually from GitHub's Actions tab.

The build job uses Python 3.13, installs the pinned requirements with
`make setup`, and runs `make check` to generate and validate the reader. It then
uploads **only `dist/`** as the Pages artifact. The deployment job runs only for
`master` and uses the `github-pages` environment. Action references are pinned to
commit hashes; comments identify their major versions. Pip downloads are cached
using `requirements.txt` as the dependency key.

This workflow does not run recovery or access Wayback/Arquivo. It needs the
saved `archive/` and `content/` files, generator, tests, styles, and requirements
in the pushed commit. `dist/` remains Git-ignored and is rebuilt on the runner.
The site uses relative links, so the `/blimpyb/` project prefix needs no special
build setting. There is no Jekyll stage or Python server on the published site.

A local workflow file does not publish until it is committed and pushed. The
URL may return 404 before the first successful deployment. Check the **Deploy
GitHub Pages** run in Actions when publication fails: a failed build/check stops
deployment, while a deployment error can indicate Pages or environment settings.
Keep Settings → Pages → Source set to GitHub Actions. If the default branch is
renamed, update both the push trigger and deployment condition in the workflow.

### Baseline and count meanings

| Observation | November 2, 2026 baseline |
| --- | ---: |
| Full article texts in the reader | 164 |
| Original gallery pages in the reader | 66 |
| Original About page | 1 |
| Generated tag pages | 512 |
| Total generated HTML pages, including the three root pages | 746 |
| Image files copied into the reader | 751 |
| Upload families in the all-uploads collection | 749 |
| Distinct preserved image payloads in `archive/assets/` | 821 |
| Successful image URL records in `archive/images.json` | 825 |
| Successful HTML records in `archive/pages.json` | 260 |
| Successful feed records in `archive/feeds.json` | 32 |
| Known article texts still incomplete | 13 |
| Unrecovered image occurrences across rendered source documents | 1,639 |

These numbers measure different things. Multiple URLs can return identical
bytes; multiple sizes can belong to one photo; the same missing photo can occur
on several pages. Some gallery pages have no recovered pictures. The HTML
manifest also contains monthly indexes and other evidence that is not published
as a reader page. Failed individual-page requests can be covered by full text
from a feed, so the 18 failed page records do not mean 18 missing articles.

Use `dist/recovery.json` for current derived counts, per-document sources, image
matches, and outstanding gaps. It is regenerated, not an input to the build.
For a quick inspection without dumping every document:

```sh
.venv/bin/python - <<'PY'
import json
from pathlib import Path
r = json.loads(Path('dist/recovery.json').read_text())
for key in ('articles', 'galleries', 'tag_pages', 'local_image_files', 'image_families'):
    print(key, r[key])
print('incomplete_article_texts', len(r['unrecovered_articles']))
print('missing_image_occurrences', sum(len(d['missing']) for d in r['documents']))
PY
```

## 3. Repository map

| File or directory | Responsibility |
| --- | --- |
| [scripts/recover.py](scripts/recover.py) | URL identity helpers, archive requests, validation, resumable manifests, and recovery phases. |
| [scripts/discover.py](scripts/discover.py) | Offline discovery of article IDs and image families absent from the primary inventory; consumes saved map markers too. |
| [scripts/build.py](scripts/build.py) | Source selection, HTML extraction, image selection, link rewriting, tag membership, templates, and output reports. |
| [web/style.css](web/style.css) | Reader appearance, mobile layout, galleries, tag lists, and print styles. |
| [web/reader.js](web/reader.js) | In-page search/filter/sort behavior and showing or hiding missing gallery pictures. |
| [scripts/check.py](scripts/check.py) | Generated link/resource checks, image decoding, and preserved-payload hash checks. |
| [tests/test_archive.py](tests/test_archive.py) | Regression coverage for URL/article identity, image families, full feed content, HTML cleaning, and tag membership/link rewriting. |
| [.github/workflows/ci.yaml](.github/workflows/ci.yaml) | Build and validate pull requests with `make check`. |
| [.github/workflows/pages.yaml](.github/workflows/pages.yaml) | Build, validate, and publish `dist/` to GitHub Pages on pushes to `master`. |
| `archive/indexes/` | Saved CDX/search responses and notes about successful and unsuccessful investigations. |
| `archive/raw/` | Downloaded HTML, XML feeds, and `map-data.html`. |
| `archive/assets/` | Validated image payloads named using a prefix of their content hash. |
| `archive/pages.json`, `archive/feeds.json`, `archive/images.json` | Download manifests; see the schema notes below. |
| `archive/map.json`, `archive/map-locations.json` | Provenance for the saved map response and 143 extracted location markers. |
| `archive/leads.json` | Derived discovery output; the build uses its article leads to report missing texts. |
| `dist/articles/`, `dist/galleries/`, `dist/pages/`, `dist/tags/` | Generated static pages. |
| `dist/images/` | Copies of selected images, not newly synthesized or resampled pictures. |

Back up the code, `web/`, `archive/`, and `content/`. `dist/` is self-contained
for reading and copying elsewhere, but it is not a substitute for the raw
evidence needed to improve extraction later. `dist/` and `.venv/` are ignored by
Git; preserved evidence is intended to remain with the project.

## 4. How the recovery was performed

### Earlier mirror and inventory discovery

The original [fetch.rb](fetch.rb) walked at most five front-page pagination
pages and stopped after 30 encountered entries. The existing result contained
28 Markdown articles and eight files named as images. Only six were real JPEGs:
the two Quartzsite files named `IMG_4851.jpg` and `IMG_4858.jpg` contained empty
HTML responses. They remain in the historical mirror, but are not served as
images by the new reader. The Ruby scraper is not the current build pipeline.

The new approach first queried the Wayback CDX URL index for `blimpyb.com/*`,
successful HTTP captures, `collapse=urlkey`, and captures through 2016. The saved
[primary inventory](archive/indexes/wayback.json) has 1,792 records. This discovers
URLs independently of the links exposed by one homepage snapshot.

`targets()` selects historic article routes, individual gallery pages, monthly
indexes, selected site pages, uploads, and SolarPress theme images. It also
includes the source captures referenced by the original Markdown and a known
homepage capture. It does not indiscriminately import every HTML URL: `/wpinc/`
spam and later reuse of the domain are outside this archive's scope.

The primary inventory is a JSON array whose first row names the columns. It is
not a list of objects, and CDX `urlkey` is not the same representation as the
project's `url_key()` result. Use `inventory()` to turn its rows into dictionaries.
`collapse=urlkey` provides URL coverage, not every historical revision of a page.

### Full text from feeds and other surviving evidence

The main feed was queried with `collapse=digest` to find distinct content across
captures, rather than keeping only one response for its URL. A category-feed
query extended that search. The final saved set contains 17 main RSS captures,
14 category RSS captures, and one Atom capture.

Six bodies absent from the reader's individual-page sources came from RSS:

- Calgary Stampede 2011: Staring at the Sun
- I'd like to buy a prostitute license, please
- Album of the Week: Midnite Vultures by Beck
- Album of the Week: Kick by INXS
- Trader Joe's and Drive-Thru Banking
- Crazy speakers

Only RSS `content:encoded` and Atom HTML `content` are accepted as full bodies.
RSS `description`, Atom `summary`, and monthly/category excerpts are not promoted
to full articles. The additional category snapshots and Atom feed mostly
overlapped already recovered articles, but remain useful preserved evidence.

`discover.py` scans saved links for article IDs absent from the primary index.
It also consumes the old Geo Mashup travel-map data. That map response was
recovered separately, retained as `archive/raw/map-data.html`, and its 143
markers were extracted into `archive/map-locations.json`. Six further article
IDs were found through the map, but their archived `?p=ID` requests did not
produce the requested bodies. The map is evidence for discovery, not a live map
feature, and its obsolete Google Maps scripts are not run.

The map retrieval/extraction was a separate investigation; there is currently
no `recover.py map` phase. Preserve its manifest and payload when changing
discovery, and document any future repeatable extraction tooling.

### Image recovery

The selected primary image inventory contains 819 URLs, all recovered by the
end of the sweep. That does **not** mean every original site photograph was
captured: many image references in saved pages have no usable indexed payload.

Several techniques increased coverage:

1. Recover WordPress resized images and PageSpeed variants, even when their
   original full-size URL is absent. Use decoded dimensions rather than trusting
   the dimensions embedded in the filename.
2. Request raw Wayback replay with `id_`. Three indexed image URLs returned 404
   in this mode but worked with `im_`; `fetch()` now tries that fallback for image
   raw-replay 404s. The exact final replay URL is kept in the manifest.
3. Check Arquivo.pt independently. Its homepage text search returned no results,
   but its URL index held 18 capture records with duplicates from an imported
   Internet Memory collection. Nine image URL records were recovered there,
   including four URLs outside the primary Wayback inventory.
4. Inspect external image URLs used by the articles. Two external images were
   recovered, including the Beck cover discussed below. Three other Apple
   artwork URLs and one Facebook photo remained unavailable after both replay
   modes were tried.

The recovery normally restricts blog captures to the historic period through
2016. There is a deliberate exception for an **external image** whose exact
normalized original URL is unchanged: the Beck *Midnite Vultures* cover survives
at its original Apple CDN URL in a 2025 capture. It was visually checked, and
the manifest records that actual source and `later_capture`. This exception is
not permission to import later content hosted on blimpyb.com.

Every accepted image is opened with Pillow, verified, and decoded. HTTP 200,
a `.jpg` suffix, and `Image.verify()` alone are insufficient; the earlier empty
HTML files and the need to decode JPEG pixels motivated these checks.

### Investigations that did not add content

Details and query URLs are retained in
[archive/indexes/investigation.json](archive/indexes/investigation.json):

- Common Crawl queries covering 2012–2016, including an exact homepage query,
  returned HTML 504 responses. This avenue is unresolved, not evidence of zero
  coverage. Some saved files end in `.json` but contain the actual HTML error
  response; do not assume every file under `indexes/` parses as JSON.
- An all-years Wayback upload inventory found later unrelated domain content
  and an HTML response at an old photo URL, not additional historic photos.
- Alternative `if_` HTML replay for two missing articles still returned 404.
- A public CDX query for the underlying WARC filename/offset of a failing image
  returned null fields. The image was later recovered with `im_` instead.
- Several exact web searches for other copies produced no results.

## 5. Manifest identity and provenance

The page, image, and feed manifests are JSON **objects keyed by record identity**.
`record_key()` uses `url_key(original)` for pages/images, and appends
`@timestamp` for feeds so multiple snapshots of one feed survive.

`original_url()` removes a Wayback replay wrapper and normalizes the historical
`:80` domain spelling. `url_key()` ignores HTTP versus HTTPS, removes a leading
`www.`, decodes the path, strips a trailing slash, and retains the query string.
It is the project's lookup key, not a fetch URL. `article_id()` recognizes the
old numeric WordPress IDs in article paths and root `?p=ID` links, only on the
original site's hostnames. Category/date/tag/gallery routes are not articles.

Common record fields:

| Field | Meaning |
| --- | --- |
| `original` | Original resource URL, before the archive replay wrapper. |
| `timestamp` | Selected/requested capture timestamp; do not assume it is the final capture after a redirect. |
| `kind` | `page`, `feed`, or `image`. |
| `source` | Replay URL; successful newer records retain the effective URL returned by curl. |
| `requested_source` | Initial replay URL when recorded. Some early records predate this field. |
| `retrieved_at` | Retrieval time, distinct from publication date and capture time. |
| `status` | `ok` or `failed`. |
| `path`, `sha256`, `bytes` | Repository-relative payload path, full SHA-256 of its bytes, and byte count for successful records. |
| `width`, `height` | Decoded image dimensions. |
| `error` | Failure detail. A failed attempt is not proof of permanent absence. |
| `provider`, `discovered_in`, `http_status`, `later_capture` | Additional provenance when available; not required on every old record. |

Preserve unknown CDX/provider fields when updating records. `digest` from CDX
and `sha256` computed locally are different fields; do not interchange them.

Image filenames use the first 20 characters of the **payload SHA-256**, with an
extension determined from the decoded format. HTML filenames instead hash the
**normalized URL key**; feed filenames hash the URL-plus-timestamp record key.
Thus an HTML filename is not a content hash. `map-data.html` is a named exception.
Always verify against the manifest's full `sha256`.

`archive/map.json` is a single provenance object, not a keyed collection, and
does not have the same mandatory fields as the download manifests. The checker
handles it separately. `map-locations.json` is derived data, and is not itself
one of the payloads hash-checked through that manifest.

The normal page/image manifests keep one record per normalized URL. They are
not a general multi-version store. For a better capture of an already successful
URL, preserve the old record and bytes before deliberately changing selection
or extending the schema; deleting evidence to force a download loses history.

## 6. How the reader is generated

### Source selection: `load_documents()`

The precedence is implemented in this order:

1. Read the original Markdown with TOML front matter, keyed by WordPress article
   ID. This supplies a fallback.
2. Read successful HTML records in timestamp order. For an article, require
   the matching `#post-ID`, an `.entry`, a title, and a parseable publication
   date in `.clock`. Matching full HTML replaces the fallback. Gallery and About
   pages use their original paths as identities and do not require article dates.
3. Read feeds newest capture first. `feed_documents()` extracts full bodies;
   `setdefault()` fills only IDs not already selected. It does not overwrite an
   existing Markdown or HTML document merely because a feed is newer or longer.

Categories come from `.categoryb a` in HTML. WordPress feeds mix categories and
tags in the same XML field, so feed terms matching the known HTML category names
are treated as categories and the remainder as tags. This is a corpus-specific
classification heuristic, not a universal WordPress taxonomy decoder.

Documents are sorted newest first. Generated article paths combine publication
date and a title-derived slug; galleries/pages use a title slug without a date.
Changing a title or slug policy changes its generated URL. Internal links are
rebuilt, but external bookmarks may need aliases if stable URLs matter.

`unrecovered_articles()` compares discovery leads with selected document IDs and
retains the longest available excerpt from saved pages. These appear in the
preservation report, not in the full article count.

### Image selection: `Assets` and `image_family()`

`image_family()` removes known PageSpeed prefixes/suffixes and WordPress
`-WIDTHxHEIGHT` suffixes while retaining the hostname, upload directory, and base
filename. For example, variants of `2012/02/IMG_7430.jpg` can match each other;
`2010/02/IMG_7430.jpg` must remain a separate family.

`Assets.find()` chooses the matching saved variant with the largest decoded
pixel area. This need not be the original resolution or uncropped composition.
If a thumbnail reference is unavailable but its parent link identifies a saved
image, the parent image can supply the display copy. Legacy image fallback is
restricted to the original article's own image directory; never broaden it to
a global search for `IMG_1234.jpg`.

`Assets.local()` copies selected bytes to `dist/images/` using content-derived
names. No image generation, enhancement, or resampling occurs. The photo-library
page also exposes the largest copy of every recovered upload family, including
uploads whose parent pages were not recovered. Saved theme assets are not all
necessarily displayed.

### Tags: `collect_tags()`

Tag membership comes from original `a[rel~=tag]` links to `/tag/SLUG/` and from
feed metadata, not from words appearing in an article body. Both articles and
galleries can be members of a tag page. Run this collection **before HTML
cleaning**, because cleaning strips attributes such as `rel`.

Explicit tags are grouped by decoded, case-folded original slug. Feed tag names
are matched case-insensitively to known labels where possible; otherwise a new
feed tag identity is created. Membership is deduplicated per document. When
different identities normalize to the same output filename, a short hash suffix
keeps their pages distinct.

The resulting original-URL-to-local-path map is merged into the link map before
article rendering. Original footer links then point to `../tags/NAME.html`.
Feed-only tags are appended as generated linked footers. Tag pages are ordinary
static lists and work with JavaScript disabled; there is no separate tag API.

### Content cleaning, link rewriting, and templates

`prepare_content()` uses BeautifulSoup to remove historic scripts, styles,
forms, trackers, adverts, and unsupported active embeds. Recognized YouTube and
Vimeo embeds become external watch links. It preserves prose and captions,
normalizes WordPress gallery structures, and replaces unrecovered pictures with
captioned placeholders.

Image resolution happens before general anchor rewriting, while original image
and parent-link URLs are still available. Links then resolve to local articles
by URL or WordPress ID, local galleries/site pages/tags by URL, and saved images
by family. Unrecovered destinations on the original domain point to Wayback;
ordinary external links remain external. HTML elements and attributes are then
reduced to an allowlist. New generated markup must still escape source text.

`layout()` provides the shared shell. `build()` renders documents and tag lists,
then the root article index, gallery/photo library, preservation notes, and
`recovery.json`. The current three root HTML pages are `index.html`,
`galleries.html`, and `recovery.html`.

Search data is embedded in each article-index row as data attributes. The local
script matches every whitespace-separated query token as a case-insensitive
substring, then applies exact year/category filters and date sorting. It is not
an exact-phrase search. Query parameters are read on load; history updates are
skipped for `file://`. Avoid introducing a runtime JSON fetch that would make
the reader depend on an HTTP server.

### Trace a specific article

For “Westport and the Docks of the Damned”:

- The source HTML is
  [archive/raw/ee6b4cc314f2382e1500.html](archive/raw/ee6b4cc314f2382e1500.html).
- After a build, its reader path is
  `dist/articles/2010-09-29-westport-and-the-docks-of-the-damned.html`.
- Find that path in `dist/recovery.json` to see its `original`, `source`,
  `raw_path`, image matches, and missing references.
- Use `archive/pages.json` for the source payload's hash and retrieval details.
  Use `archive/images.json` for individual image payload provenance.

Inspect the original source when debugging extraction, but make the durable fix
in the generator. Editing the generated HTML will disappear on the next build.

## 7. Continuing recovery without repeating everything

UI changes do not require recovery. For new evidence, run phases serially:

```sh
# Network: refresh primary URLs and distinct RSS capture inventories.
.venv/bin/python scripts/recover.py index

# Network: preserve selected HTML and full-content feeds.
.venv/bin/python scripts/recover.py pages --retry-failed
.venv/bin/python scripts/recover.py feeds --retry-failed

# Offline: refresh leads. linked-pages also does this itself.
.venv/bin/python scripts/discover.py

# Network: try unindexed article leads and recover image payloads.
.venv/bin/python scripts/recover.py linked-pages --retry-failed
.venv/bin/python scripts/recover.py images --retry-failed
.venv/bin/python scripts/recover.py external-images --retry-failed
.venv/bin/python scripts/recover.py arquivo --retry-failed

# Offline: regenerate and validate the reader.
make check
```

`make recover` runs `index`, `pages`, `feeds`, `linked-pages`, `images`, and
`external-images`, in that order. It does not run the Arquivo phase, rebuild the
reader, or repeat the separate map/Common Crawl investigations.

The `arquivo` phase consumes the **saved** newline-delimited JSON response in
`arquivo-cdx-response.json`; it does not refresh Arquivo's index. The `index`
phase refreshes Wayback inventories only. `external-images` scans selected
article bodies, not arbitrary external sites or all gallery pages.

`discover.py` finds leads absent from the primary index, not necessarily absent
from every other source. An article lead may already be recovered through RSS;
an image lead may be covered by Arquivo. Its image leads are recorded for further
investigation and are **not** automatically downloaded by `linked-pages`.

Operational details:

- Successful records whose files exist are reused. This skip check does not
  rehash them; `make check` performs integrity validation.
- Failed records are skipped unless `--retry-failed` is supplied. It retries
  failures, not every successful capture.
- `--limit 10` limits the pending queue, and `--delay 10` increases request
  spacing. The default is one worker with at least five seconds between requests.
  `--workers` exists, but faster/concurrent requests were followed by temporary
  refusals during the recovery. Prefer the conservative defaults.
- A phase can exit successfully even when individual URLs failed. Inspect its
  summary and manifest statuses rather than treating exit code zero as complete
  recovery.
- Connection refusals, timeouts, HTTP 429, and HTTP 503 can trigger 310-second
  cooldowns before retrying. Three consecutive completed outage failures stop
  the queue. Do not interpret a quiet cooldown as lost progress.
- Each completed result updates the manifest via an atomic temporary-file
  replacement. Ctrl-C cancels queued work and saves completed results; an active
  request or cooldown may still need to finish while the worker shuts down.
- Run only one recovery process at a time. Pacing and locks are process-local,
  and processes sharing a manifest can overwrite each other's updates. In
  particular, `images`, `arquivo`, and `external-images` all write `images.json`.
- Index refreshes replace the saved index files. Preserve a before-copy if
  comparing coverage across investigations. Ordinary page/image records are
  likewise not an automatic revision history.

When adding a new archive source, record its query, response, capture URL,
retrieval time, exact payload hash, and validation result. Distinguish a real
negative result from a gateway failure. Extend source handling deliberately;
do not put fabricated success records into a manifest to make the build pass.

## 8. Making changes and verifying them

| Desired change | Starting point |
| --- | --- |
| Typography, spacing, mobile layout | `web/style.css` |
| Search/filter/sort or gallery toggle behavior | `web/reader.js` and corresponding generated markup in `build.py` |
| Page shell, navigation, article/tag/index layout | `layout()` and `build()` |
| Wrong title/date/body or missing feed article | `load_documents()`, `feed_documents()`, then the preserved source |
| Wrong or missing picture despite saved bytes | `image_family()`, `Assets.find()`, then the image manifest and original URLs |
| Tag points outside the archive or has wrong members | `collect_tags()` and the link map assembled before `prepare_content()` |
| A new recovery lead or alternate replay technique | `discover.py`, `recover.py`, and the investigation log |

For implementation changes, run `make check`. It currently runs seven unit tests
and checks every generated HTML page. The checker verifies local file targets,
page landmarks, image alt attributes, disallowed active elements, remote `src`
attributes and unsupported URL schemes, image decoding in both source and
generated directories, and SHA-256
integrity for successful page/feed/image/map payload records.

The checker is not a full browser, CSS audit, or external-link availability test.
It permits HTTP(S) `href` links and does not inspect CSS `url()` or `@import`
loads, so use a browser network check for changes that could introduce remote
styles or other indirect requests. It does not test fragment anchors, run
JavaScript, or verify the derived map marker JSON against its source. Add
focused verification when a change affects something beyond those checks. For
documentation-only edits, check referenced paths, commands, and factual counts;
a new network sweep is unnecessary.

Useful browser regression cases:

1. Open `dist/index.html` directly. Search for words from an article body, change
   year/category/order, and open a result. Multiword search can match several
   articles even when the query resembles one title.
2. Open a feed-only article, such as “Calgary Stampede 2011: Staring at the Sun,”
   and check its body and source disclosure.
3. Open “An Afternoon in Aberdeen.” Follow Aberdeen, Kurt Cobain, McDonald's,
   and Washington State to local tag lists and back to an article. Check the
   San Diego tag includes the RSS-recovered Trader Joe's article. Repeat tag
   navigation with JavaScript disabled.
4. Check a gallery containing both available and missing photos. The gap toggle
   should hide only missing figures and restore them when checked again.
5. Check narrow layouts around 390 pixels, including long titles and bare URLs.
   These caused horizontal overflow during development and have explicit CSS
   wrapping fixes.
6. With browser networking disabled, article reading, images, and local
   navigation should still work. Source/video links intentionally need networking.

The initial reader was checked in headless Chrome using Playwright, including
all then-generated pages at phone width; the tag update was checked through the
specific navigation paths above with networking and JavaScript disabled.
Playwright is optional development tooling, not a dependency in
`requirements.txt`, and temporary screenshots/scripts from that session are not
part of this repository. Reproduce relevant checks in an available browser.

When finished with a change, regenerate `dist/`, inspect the relevant output,
and update this guide or the README if commands, source selection, schemas, or
preservation behavior changed. Update reported counts only from a fresh build;
do not change the counts merely to conceal an extraction regression.
