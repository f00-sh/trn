# TRN

**[trn.f00.sh](https://trn.f00.sh)** — Enhanced Tabular Recipe Notation (eTRN) converter.

Convert any recipe into a dense process matrix: **ingredient rows** × **chronological stages**, inspired by [Cooking for Engineers](https://www.cookingforengineers.com/) Tabular Recipe Notation.

> **Status:** v0.1.0. Live on Cloudflare Pages. Rule-based path works offline; optional LLM path (xAI / OpenAI-compatible) for high-quality stage labels.

## What you get

| Output | Description |
|--------|-------------|
| **TRN table** | Scannable Markdown/HTML matrix |
| **eTRN JSON** | Structured export (`meta`, `ingredients`, `stages`, …) |
| **Printable view** | Clean HTML for browser Print → Save as PDF |

**Inputs:** recipe URL and/or pasted title + ingredients + instructions.

**Conversion paths**

1. **Rule-based** — always available, zero cost, works offline (paste) / with fetch (URL).
2. **LLM** — optional; paste an xAI or OpenAI-compatible API key (default `https://api.x.ai/v1`, model `grok-3`).

## Hosting

Cloudflare is the delivery plane for the product site:

| Surface | Host |
|---------|------|
| Site + converter | Cloudflare Pages project `f00-trn` → https://trn.f00.sh |
| URL scrape | Pages Function `POST /api/scrape` |
| Local Streamlit | `app.py` on your machine |

GitHub holds source and releases only.

## Quick start (local Streamlit)

```bash
pip install streamlit recipe-scrapers openai requests beautifulsoup4
streamlit run app.py
```

Or:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Quick start (site)

Open https://trn.f00.sh — or from a clone:

```bash
npx wrangler pages dev site
```

## Deploy

```bash
npx wrangler pages deploy site --project-name=f00-trn --branch=main
```

CI: [`.github/workflows/pages.yml`](.github/workflows/pages.yml) deploys on push to `site/**` or `functions/**`.

## How to read a TRN table

1. **Rows** = ingredients (first-use order).
2. **Columns** = short chronological stages (`melt`, `cream`, `bake 350°F 25min`).
3. **Cells** = concise action for that ingredient in that stage; empty = idle.
4. Read a **row** left→right to follow one ingredient; read a **column** for one stage.
5. Critical temps, times, and *until…* conditions stay in labels or cells.

## Layout

| Path | Role |
|------|------|
| [`app.py`](app.py) | Single-file Streamlit app |
| [`site/`](site/) | Public converter (Pages) |
| [`functions/api/scrape.js`](functions/api/scrape.js) | URL extraction |
| [`requirements.txt`](requirements.txt) | Python deps |
| [`man/trn.1.md`](man/trn.1.md) | Man page source |

## Documents

| Doc | Path |
|-----|------|
| Operator SOP (NASA) | [`docs/sop-trn-ops.pdf`](docs/sop-trn-ops.pdf) · [JSON](docs/sop-trn-ops.json) |
| Release memo 0.1.0 | [`docs/releases/v0.1.0-memo.pdf`](docs/releases/v0.1.0-memo.pdf) · [JSON](docs/releases/v0.1.0-memo.json) |
| Changelog | [`CHANGELOG.md`](CHANGELOG.md) |
| Site | [https://trn.f00.sh](https://trn.f00.sh) |
| Man page | [`man/trn.1.md`](man/trn.1.md) |
| Scene card | [`file_id.diz`](file_id.diz) |

## Scene card

```text
░▒▓████████████████████████████████████████████▓▒░
█▓▒░  T R N  ·  scene card  ·  v0.1.0  ░▒▓█
████████████████████████████████████████████████████
█  tabular recipe notation · eTRN process matrix  █
█  ingredient rows × chronological stages         █
█  rule-based · optional grok/openai llm          █
█  site: trn.f00.sh  ·  github: f00-sh/trn        █
█  MIT  ·  f00  ·  2026                           █
░▒▓████████████████████████████████████████████▓▒░
```

## Configuration

| Setting | Default | Notes |
|---------|---------|--------|
| LLM base_url | `https://api.x.ai/v1` | Sidebar / site LLM panel |
| LLM model | `grok-3` | Or `grok-3-mini` / any chat model |
| API key | (none) | User-supplied; never committed |

See [`.env.example`](.env.example). Do not put real keys in git.

## Security

See [SECURITY.md](SECURITY.md). Report vulnerabilities privately.

## License

[MIT](LICENSE) © f00
