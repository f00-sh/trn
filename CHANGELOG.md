# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-07-29

### Added

- Single-file Streamlit converter (`app.py`): URL and paste input, rule-based eTRN matrix, optional LLM path (xAI/OpenAI-compatible).
- Rule-based path: ingredients as rows, instruction stages as columns, keyword action cells, Markdown table + eTRN JSON + printable HTML.
- LLM path: exact eTRN system prompt; default `https://api.x.ai/v1` and model `grok-3`.
- Extraction: `recipe-scrapers` primary; JSON-LD schema.org/Recipe fallback; paste parser with Ingredients/Instructions headers.
- Cloudflare Pages site (`site/`) with f00 phosphor UI, client rule-based converter, optional browser LLM, download JSON/HTML, print view.
- Pages Function `POST /api/scrape` for CORS-safe URL extraction.
- House docs pack: README, man, SOP, release memo, file_id.diz, Pages deploy workflow.

## [Unreleased]

### Added

- (none yet)
