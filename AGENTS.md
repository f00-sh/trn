# TRN

## Project name

**TRN** — Enhanced Tabular Recipe Notation converter (eTRN).

- Site: https://trn.f00.sh
- Repo: f00-sh/trn (org: **f00-sh**)
- Hub: https://f00.sh (product card)

## Declared language

**Python** (Streamlit local app) + **static HTML/CSS/JS** for Cloudflare Pages delivery.

- Local converter: pure Python deps only (`streamlit`, `recipe-scrapers`, `openai`, `requests`, `beautifulsoup4`).
- Edge site: static `site/` + Pages Function `functions/api/scrape.js` (no Node app server).
- Style: `~/.grok/references/coding-standards/python.md` for Python.

## Product laws

1. **Simplest working converter.** URL or paste → eTRN matrix (Markdown table + JSON + printable HTML).
2. **Two conversion paths.** Rule-based always works offline. LLM path is optional (user key; default xAI `https://api.x.ai/v1`, model `grok-3`).
3. **Cloudflare is the delivery plane** for the product site. GitHub holds source/history only (no GitHub Pages).
4. **No auth, no database, no secrets in repo.** User pastes API keys client-side / Streamlit session only.
5. **f00 aesthetic** on the public site: Heartbox palette (default f00 theme) via https://f00.sh/theme/f00-theme.css — Onyx brand, zine body, chip chrome (dense tables OK; no phosphor green).
6. **Documentation pack is automatic** on every release (NASA SOP PDF, this-version memo PDF, CHANGELOG, README, Pages, man, file_id.diz).

## Layout

| Path | Role |
|------|------|
| `app.py` | Single-file Streamlit converter (local) |
| `requirements.txt` | Python deps |
| `site/` | Cloudflare Pages static app → https://trn.f00.sh |
| `functions/api/scrape.js` | Pages Function: URL → JSON-LD recipe extract |
| `wrangler.toml` | Pages project `f00-trn` |
| `docs/` | SOP, release memos, Pages mirror notes |
| `man/trn.1.md` | Man page source |
| `file_id.diz` | Scene card |

## Edge (Cloudflare)

- **Pages project:** `f00-trn` → custom domain `trn.f00.sh`
- **Deploy:** push `site/**` / `functions/**` → workflow `pages.yml`, or `npx wrangler pages deploy site --project-name=f00-trn --branch=main`
- **Account:** f00 Cloudflare (tj@f00.sh)

## Commands

```bash
# Local Streamlit
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py

# Static site (open site/index.html or wrangler pages dev)
npx wrangler pages dev site --compatibility-date=2026-07-01
```

## Install channels

- Product is a web app + optional local Streamlit. No native binary.
- Curl install.sh is a thin helper for local Streamlit setup only.
- Package managers: none yet.

## Releases

- Every SemVer release: CHANGELOG, file_id.diz, README + docs triad, NASA SOP PDF, this-version NASA memo PDF, GitHub Release assets, f00 hub product card if first ship or copy change.

## Visual law (all f00 products)

- **Contrasts:** Nirvana *Heart-Shaped Box* video / Heartbox palette — hospital-night bg, cream fg, poppy accent, verse sky, silver metal.
- **Text & boxes:** Nirvana *Bleach* album — hard square frames, catalog mono labels, no rounded glass, thin rules, raw liner-note density.
- **ONE shared org CSS:** `https://f00.sh/theme/f00-theme.css` (hub domain; all subdomains). Product CSS = layout only (do not invent brand hex or soft UI radii).
