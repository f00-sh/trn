# trn(1) — Enhanced Tabular Recipe Notation converter

## NAME

trn — convert recipes into Enhanced Tabular Recipe Notation (eTRN)

## SYNOPSIS

```text
streamlit run app.py
# or use the site
# https://trn.f00.sh
```

## DESCRIPTION

TRN converts a traditional recipe into a dense process matrix.

Rows are ingredients in first-use order.
Columns are chronological process stages with short labels.
Each cell is a concise action for that ingredient in that stage.
Empty cells mean the ingredient is idle.

You may supply a recipe URL or paste the full recipe text.
Paste is the reliable path when a site blocks scrapers.

Two conversion paths exist:

1. Rule-based — always available, zero cost.
2. LLM — optional. You supply an API key for an OpenAI-compatible endpoint.
   Default base URL is `https://api.x.ai/v1`.
   Default model is `grok-3`.

Outputs:

- Markdown / HTML TRN table
- Downloadable eTRN JSON
- Printable HTML for browser Print → Save as PDF

## OPTIONS

Streamlit UI controls (no CLI flags in v0.1.0):

```text
URL field
    Recipe page URL. Uses recipe-scrapers, then JSON-LD fallback.

Paste area
    Full recipe text with Ingredients and Instructions sections.

Convert
    Run extraction and conversion.

Sidebar: High-quality LLM path
    Enable LLM conversion. Requires API key.

Sidebar: API key / base_url / model
    OpenAI-compatible chat completions settings.
```

Site UI mirrors the same controls at https://trn.f00.sh.

## EXIT STATUS

| Code | Meaning |
|------|---------|
| 0 | Streamlit process exited cleanly |
| non-zero | Process or dependency failure |

## ENVIRONMENT

| Variable | Purpose |
|----------|---------|
| (none required) | API keys are entered in the UI session only |

## FILES

| Path | Purpose |
|------|---------|
| `app.py` | Streamlit application |
| `requirements.txt` | Python dependencies |
| `site/` | Cloudflare Pages static converter |
| `functions/api/scrape.js` | URL scrape function |
| `file_id.diz` | Release scene card |

## EXAMPLES

```text
# Install and run local converter
pip install streamlit recipe-scrapers openai requests beautifulsoup4
streamlit run app.py

# Use the hosted product
# open https://trn.f00.sh
```

## SEE ALSO

- [README.md](../README.md)
- [CHANGELOG.md](../CHANGELOG.md)
- [file_id.diz](../file_id.diz)
- Site: https://trn.f00.sh
- Hub: https://f00.sh

## BUGS

Report issues at https://github.com/f00-sh/trn/issues.
Do not file security issues in public trackers; see [SECURITY.md](../SECURITY.md).
