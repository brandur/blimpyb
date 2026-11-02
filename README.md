# BlimpyB archive

A local, offline reading copy of **Blimpy Backgammon**, formerly at
blimpyb.com. It preserves the author's writing and photographs in a new static
reader, with full-text search, year and subject filters, local tag pages, and
photo galleries.

**Online archive:** [brandur.github.io/blimpyb](https://brandur.github.io/blimpyb/).
GitHub Pages publishes updates automatically when changes are pushed to `master`.

The November 2, 2026 recovery contains **164 articles, 66 gallery pages, and
751 image files**, expanded from an earlier mirror of 28 articles and six usable
images. Material was recovered from the Internet Archive, Arquivo.pt, and saved
feeds.

The archive remains incomplete: **13 known article texts** and many photographs
are still missing, and some photos survive only as thumbnails. The reader's
preservation page documents these gaps and links to source captures.

## Read locally

Requires Python **3.11 or newer** and `make`:

```sh
make setup
make serve
```

Open **http://127.0.0.1:8000**. Press Ctrl-C to stop the server. Setup installs
dependencies once; building and reading then work offline. Source links and
videos still require internet access.

Alternatively, run `make build` and open `dist/index.html` directly in your
browser. The generated `dist/` directory is self-contained and can be copied
to another machine or ordinary static hosting.

## Development

Preserved captures and provenance live under `archive/`; the earlier mirror
remains under `content/`. The reader is generated from these sources, Python
scripts, and the assets in `web/`. Changes to `dist/` are overwritten on rebuild.

Run `make check` to rebuild and validate the archive. Pull requests run the same
build and checks automatically in GitHub Actions.

For maintainers and coding agents, [MAINTENANCE.md](MAINTENANCE.md) describes the
recovery methods, data formats, build internals, validation, and how to continue
recovery or modify the reader.

The original prose and photographs belong to their respective creators.
