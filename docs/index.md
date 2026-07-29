# TRN

**[trn.f00.sh](https://trn.f00.sh)** — Enhanced Tabular Recipe Notation converter.

Ingredient rows × chronological stages. Cooking for Engineers–style process matrices.

## Product

| Surface | URL / path |
|---------|------------|
| Live site | https://trn.f00.sh |
| Source | https://github.com/f00-sh/trn |
| Local app | `streamlit run app.py` |

## Documents

| Doc | Path |
|-----|------|
| Operator SOP (NASA) | [sop-trn-ops.pdf](sop-trn-ops.pdf) · [JSON](sop-trn-ops.json) |
| Release memo v0.1.0 | [releases/v0.1.0-memo.pdf](releases/v0.1.0-memo.pdf) · [JSON](releases/v0.1.0-memo.json) |
| Changelog | [../CHANGELOG.md](../CHANGELOG.md) |
| Scene card | [../file_id.diz](../file_id.diz) |

## Install (local)

```bash
pip install streamlit recipe-scrapers openai requests beautifulsoup4
streamlit run app.py
```

## How to read a TRN table

- **Rows** = ingredients (first use order)
- **Columns** = chronological stages
- **Cells** = short actions; empty = idle

## Version

v0.1.0 · MIT · f00
