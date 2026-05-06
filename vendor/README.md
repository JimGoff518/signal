# Vendored dependencies

Third-party source we ship in-tree so we control the version forever and
don't need network access to install.

## crawl4ai (v0.8.6)

LLM-friendly web crawler — Playwright under the hood, returns clean Markdown
chunks instead of raw HTML. Source: <https://github.com/unclecode/crawl4ai>.

**When we use it:** Phase 2 only — Reddit threads, CarComplaints.com pages,
NHTSA recall detail pages. Phase 1 does not depend on it.

**How to install for local dev:**

```bash
pip install -e vendor/crawl4ai
playwright install chromium      # one-time browser download
```

**How to upgrade:** drop a newer release zip from
<https://github.com/unclecode/crawl4ai/releases> on top of `vendor/crawl4ai/`,
test, commit. Don't `pip install crawl4ai` from PyPI — that will conflict
with the editable install above.

**License:** Apache 2.0. See `vendor/crawl4ai/LICENSE`.
