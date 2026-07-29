#!/usr/bin/env python3
"""TRN — Enhanced Tabular Recipe Notation converter (Streamlit).

Accepts a recipe URL or pasted text, extracts title/ingredients/instructions,
and builds a dense process matrix (ingredient rows × chronological stages).

Paths:
  1. Rule-based (always available, offline, zero cost)
  2. Optional LLM path via OpenAI-compatible client (default: xAI Grok)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

APP_VERSION = "0.1.0"
DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-3"

LLM_SYSTEM_PROMPT = """You are an expert at converting traditional recipes into Enhanced Tabular Recipe Notation (eTRN) inspired by Cooking for Engineers' Tabular Recipe Notation.
Output ONLY valid JSON with this structure:
{
"meta": {"title": "", "yield": "", "source": "", "total_times": {"active": "", "passive": "", "total": ""}},
"equipment": [],
"mise_en_place": [{"item": "", "notes": ""}],
"ingredients": [{"id": "i0", "qty_us": "", "qty_metric": "", "name": "", "prep": "", "raw": ""}],
"stages": [{"id": "st1", "label": "short label", "duration": "", "temp": null, "equipment": [], "actions": {"i0": "concise action ≤8 words"}, "produces": ""}],
"notes": [],
"markdown_table": "full ready-to-render Markdown table with | Ingredient | Stage1 | Stage2 | ... |"
}
Rules:

Rows = ingredients ordered by first use. Prefer dual units.
Columns = chronological process stages (5–10 stages). Labels very short (e.g. "melt", "cream", "fold", "bake 350°F 25min").
Cells = extremely concise action for that ingredient in that stage, or empty.
Separate pure mise-en-place when clear.
Preserve every critical temperature, time, and "until ..." condition.
Make markdown_table dense and scannable like classic Cooking for Engineers tables.
"""

# Verb keywords used by the rule-based stage classifier
ACTION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("prep", ["chop", "dice", "mince", "slice", "peel", "grate", "zest", "measure", "combine dry", "sift"]),
    ("melt", ["melt", "soften"]),
    ("heat", ["heat", "warm", "preheat", "bring to"]),
    ("saute", ["saute", "sauté", "fry", "brown the", "until brown", "sear", "sweat"]),
    ("mix", ["mix", "stir", "whisk", "beat", "cream", "fold", "combine", "blend"]),
    ("simmer", ["simmer", "boil", "poach", "reduce", "braise", "stew"]),
    ("bake", ["bake", "roast", "broil", "grill", "toast", "oven"]),
    ("rest", ["rest", "cool", "chill", "refrigerate", "freeze", "marinate", "proof", "rise", "sit"]),
    ("finish", ["serve", "plate", "garnish", "drizzle", "top", "season", "adjust", "transfer", "pour"]),
]

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "into", "with", "for", "on",
    "until", "about", "over", "under", "by", "from", "as", "at", "is", "are",
    "be", "been", "being", "cup", "cups", "tbsp", "tsp", "tablespoon", "teaspoon",
    "tablespoons", "teaspoons", "ounce", "ounces", "oz", "lb", "lbs", "pound",
    "pounds", "g", "kg", "ml", "l", "optional", "plus", "more",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Recipe:
    title: str = "Untitled recipe"
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    yield_: str = ""
    source: str = ""
    total_time: str = ""
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _clean_lines(text: str) -> list[str]:
    lines = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[\-\*\u2022\u2023\u25E6]+\s+", "", s)
        s = re.sub(r"^\d+[\.\)]\s+", "", s)
        s = s.strip()
        if s:
            lines.append(s)
    return lines


def parse_pasted_recipe(text: str) -> Recipe:
    """Best-effort parse of free-form recipe paste (title + ingredients + steps)."""
    text = text.strip()
    if not text:
        return Recipe()

    # Normalize section headers
    lower = text.lower()
    ing_m = re.search(r"(?im)^(ingredients?)\s*:?\s*$", text)
    inst_m = re.search(
        r"(?im)^(instructions?|directions?|method|steps?|preparation)\s*:?\s*$",
        text,
    )

    title = "Untitled recipe"
    ingredients: list[str] = []
    instructions: list[str] = []

    if ing_m and inst_m and ing_m.start() < inst_m.start():
        head = text[: ing_m.start()].strip()
        ing_block = text[ing_m.end() : inst_m.start()].strip()
        inst_block = text[inst_m.end() :].strip()
        if head:
            title = head.splitlines()[0].strip() or title
        ingredients = _clean_lines(ing_block)
        # Prefer numbered steps; else line-split; else sentence-split
        numbered = re.findall(
            r"(?ms)^\s*(?:\d+[\.\)]\s+|step\s+\d+[:\.]?\s+)(.+?)(?=^\s*(?:\d+[\.\)]|step\s+\d+)|\Z)",
            inst_block,
        )
        if numbered:
            instructions = [s.strip() for s in numbered if s.strip()]
        else:
            instructions = _clean_lines(inst_block)
            if len(instructions) <= 1 and inst_block:
                parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", inst_block)
                instructions = [p.strip() for p in parts if p.strip()]
    else:
        # No clear headers: first non-empty line = title, rest heuristic
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return Recipe(raw_text=text)
        title = lines[0]
        body = lines[1:]
        # Split at a blank-line style gap if original had double newlines
        chunks = re.split(r"\n\s*\n", text, maxsplit=2)
        if len(chunks) >= 3:
            ingredients = _clean_lines(chunks[1])
            instructions = _clean_lines(chunks[2])
            if not ingredients and not instructions:
                ingredients = body[: max(1, len(body) // 2)]
                instructions = body[len(ingredients) :]
        else:
            # Assume first half-ish are ingredients when many short lines
            short = [ln for ln in body if len(ln) < 80]
            if len(short) >= 3:
                cut = max(1, len(body) // 2)
                ingredients = body[:cut]
                instructions = body[cut:]
            else:
                ingredients = body
                instructions = []

    return Recipe(
        title=title,
        ingredients=ingredients,
        instructions=instructions,
        raw_text=text,
    )


def extract_jsonld_recipe(html: str, source: str = "") -> Recipe | None:
    """Parse schema.org/Recipe from JSON-LD blocks."""
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        flags=re.I | re.S,
    )
    for raw in scripts:
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        candidates = data if isinstance(data, list) else [data]
        # @graph support
        expanded: list[Any] = []
        for c in candidates:
            if isinstance(c, dict) and "@graph" in c:
                expanded.extend(c["@graph"])
            else:
                expanded.append(c)
        for node in expanded:
            if not isinstance(node, dict):
                continue
            t = node.get("@type") or node.get("type")
            types = t if isinstance(t, list) else [t]
            types_l = [str(x).lower() for x in types if x]
            if not any("recipe" in x for x in types_l):
                continue
            title = str(node.get("name") or "Untitled recipe")
            yield_ = node.get("recipeYield") or node.get("yield") or ""
            if isinstance(yield_, list):
                yield_ = ", ".join(str(y) for y in yield_)
            else:
                yield_ = str(yield_ or "")

            raw_ings = node.get("recipeIngredient") or node.get("ingredients") or []
            if isinstance(raw_ings, str):
                ingredients = _clean_lines(raw_ings)
            else:
                ingredients = [str(i).strip() for i in raw_ings if str(i).strip()]

            instructions: list[str] = []
            inst = node.get("recipeInstructions") or node.get("instructions")
            if isinstance(inst, str):
                instructions = _clean_lines(inst) or [
                    s.strip() for s in re.split(r"(?<=[.!?])\s+", inst) if s.strip()
                ]
            elif isinstance(inst, list):
                for step in inst:
                    if isinstance(step, str):
                        instructions.append(step.strip())
                    elif isinstance(step, dict):
                        # HowToStep or HowToSection
                        if "itemListElement" in step:
                            for sub in step["itemListElement"]:
                                if isinstance(sub, dict):
                                    txt = sub.get("text") or sub.get("name") or ""
                                    if txt:
                                        instructions.append(str(txt).strip())
                                elif isinstance(sub, str):
                                    instructions.append(sub.strip())
                        else:
                            txt = step.get("text") or step.get("name") or ""
                            if txt:
                                instructions.append(str(txt).strip())
            instructions = [s for s in instructions if s]

            total = node.get("totalTime") or ""
            if isinstance(total, str) and total.startswith("PT"):
                total = _iso8601_duration(total)

            return Recipe(
                title=title,
                ingredients=ingredients,
                instructions=instructions,
                yield_=yield_,
                source=source,
                total_time=str(total or ""),
            )
    return None


def _iso8601_duration(value: str) -> str:
    """Rough ISO-8601 duration → human string (PTxHyM)."""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not m:
        return value
    h, mi, s = m.group(1), m.group(2), m.group(3)
    parts = []
    if h:
        parts.append(f"{int(h)} hr")
    if mi:
        parts.append(f"{int(mi)} min")
    if s and not parts:
        parts.append(f"{int(s)} sec")
    return " ".join(parts) or value


def scrape_url(url: str) -> tuple[Recipe | None, str | None]:
    """Primary: recipe-scrapers. Fallback: requests + JSON-LD / BeautifulSoup."""
    url = url.strip()
    if not url:
        return None, "Empty URL."
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, "URL must start with http:// or https://."

    # --- recipe-scrapers ---
    try:
        from recipe_scrapers import scrape_html, scrape_me  # type: ignore

        scraper = None
        err_primary: str | None = None
        try:
            scraper = scrape_me(url)
        except Exception as e:  # noqa: BLE001 — many site-specific failures
            err_primary = str(e)
            try:
                import requests

                resp = requests.get(
                    url,
                    timeout=20,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (compatible; TRN/0.1; +https://trn.f00.sh)"
                        )
                    },
                )
                resp.raise_for_status()
                scraper = scrape_html(resp.text, org_url=url)
            except Exception as e2:  # noqa: BLE001
                err_primary = f"{err_primary}; html path: {e2}"

        if scraper is not None:
            try:
                ings = list(scraper.ingredients() or [])
            except Exception:  # noqa: BLE001
                ings = []
            try:
                inst = scraper.instructions_list()
                if not inst:
                    raw = scraper.instructions() or ""
                    inst = _clean_lines(raw) if raw else []
            except Exception:  # noqa: BLE001
                try:
                    raw = scraper.instructions() or ""
                    inst = _clean_lines(raw)
                except Exception:  # noqa: BLE001
                    inst = []
            try:
                title = scraper.title() or "Untitled recipe"
            except Exception:  # noqa: BLE001
                title = "Untitled recipe"
            yield_ = ""
            try:
                y = scraper.yields()
                yield_ = str(y) if y else ""
            except Exception:  # noqa: BLE001
                pass
            total = ""
            try:
                t = scraper.total_time()
                total = f"{t} min" if t else ""
            except Exception:  # noqa: BLE001
                pass

            if ings or inst:
                return (
                    Recipe(
                        title=title,
                        ingredients=[str(i) for i in ings],
                        instructions=[str(s) for s in inst if str(s).strip()],
                        yield_=yield_,
                        source=url,
                        total_time=total,
                    ),
                    None,
                )
            return None, err_primary or "Scraper returned empty ingredients and steps."
    except ImportError:
        pass  # fall through to requests/bs4

    # --- fallback: requests + JSON-LD + light BS4 ---
    try:
        import requests
        from bs4 import BeautifulSoup  # type: ignore
    except ImportError:
        return None, "Install recipe-scrapers or requests+beautifulsoup4 to fetch URLs."

    try:
        resp = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (compatible; TRN/0.1; +https://trn.f00.sh)"
                ),
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if resp.status_code in (401, 403, 429):
            return (
                None,
                f"Site blocked scraping (HTTP {resp.status_code}). "
                "Paste the recipe text instead.",
            )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:  # noqa: BLE001
        return None, f"Could not fetch URL: {e}. Paste the recipe text instead."

    recipe = extract_jsonld_recipe(html, source=url)
    if recipe and (recipe.ingredients or recipe.instructions):
        return recipe, None

    # Last-ditch: heuristic from soup
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        title_el = soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else (soup.title.string if soup.title else "Untitled recipe")
        text = soup.get_text("\n", strip=True)
        parsed_r = parse_pasted_recipe(f"{title}\n\n{text[:12000]}")
        parsed_r.source = url
        if parsed_r.ingredients or parsed_r.instructions:
            return parsed_r, None
    except Exception as e:  # noqa: BLE001
        return None, f"Parse failed: {e}. Paste the recipe text instead."

    return (
        None,
        "No recipe found on that page (blocked, paywall, or non-recipe HTML). "
        "Paste the recipe text instead.",
    )


# ---------------------------------------------------------------------------
# Rule-based conversion
# ---------------------------------------------------------------------------


def _ingredient_name(raw: str) -> str:
    """Strip leading quantity to get a usable name token."""
    s = raw.strip()
    s = re.sub(
        r"^(?:about\s+|approx\.?\s+|approximately\s+)?[\d\s\/\.¼½¾⅓⅔⅛⅜⅝⅞\-]+"
        r"(?:\s*(?:cups?|cup|tbsp|tsp|tablespoons?|teaspoons?|oz|ounces?|lbs?|"
        r"pounds?|g|kg|ml|l|cloves?|cans?|packages?|pkgs?|sticks?|slices?|"
        r"pinch(?:es)?|dash(?:es)?|whole))?\s+",
        "",
        s,
        flags=re.I,
    )
    # Drop leading of/to
    s = re.sub(r"^(?:of\s+)+", "", s, flags=re.I)
    # Prep after comma often
    name = s.split(",")[0].strip()
    name = re.sub(r"\s+", " ", name)
    return name or raw.strip()


def _name_tokens(name: str) -> set[str]:
    toks = re.findall(r"[a-zA-Z][a-zA-Z\-']+", name.lower())
    return {t for t in toks if t not in STOPWORDS and len(t) > 2}


def _has_kw(text: str, kw: str) -> bool:
    """Word-boundary-ish keyword hit (avoids 'brown' matching 'browned')."""
    return re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", text, re.I) is not None


def _stage_label(instruction: str, index: int) -> str:
    low = instruction.lower()
    # Temp + time snippets
    temp = re.search(r"(\d{2,3})\s*°\s*([FC])", instruction, re.I)
    time_m = re.search(
        r"(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?|seconds?|secs?))",
        instruction,
        re.I,
    )
    for label, kws in ACTION_KEYWORDS:
        for kw in kws:
            if _has_kw(low, kw):
                parts = [label]
                if temp and label in ("bake", "heat", "roast", "broil", "grill"):
                    parts = [f"{label} {temp.group(1)}°{temp.group(2).upper()}"]
                if time_m and label in ("bake", "simmer", "rest", "cook", "roast"):
                    t = re.sub(r"\s+", "", time_m.group(1).lower())
                    t = t.replace("minutes", "min").replace("minute", "min")
                    t = t.replace("hours", "hr").replace("hour", "hr")
                    parts.append(t)
                return " ".join(parts)[:40]
    # Fallback: first 3–5 words, truncated
    words = re.findall(r"[A-Za-z0-9°]+", instruction)
    if not words:
        return f"step {index + 1}"
    return " ".join(words[:4]).lower()[:32]


def _cell_action(instruction: str, ing_name: str) -> str:
    """Ultra-short action fragment for one ingredient in one stage."""
    low = instruction.lower()
    name_l = ing_name.lower()
    # Find verb near ingredient mention
    for _label, kws in ACTION_KEYWORDS:
        for kw in kws:
            if _has_kw(low, kw):
                # Prefer "verb + short object hint"
                until = re.search(r"until\s+([^.;,]{3,40})", instruction, re.I)
                temp = re.search(r"(\d{2,3}\s*°\s*[FC])", instruction, re.I)
                bits = [kw]
                if temp and kw in ("bake", "heat", "roast", "preheat", "cook"):
                    bits.append(temp.group(1).replace(" ", ""))
                if until and kw in ("cook", "bake", "simmer", "brown", "stir", "whisk"):
                    bits.append("until " + until.group(1).strip()[:24])
                # If instruction is short, use a clipped form
                if len(instruction) < 60:
                    return instruction.strip()[:48]
                return " ".join(bits)[:48]
    # Generic: clip instruction around the name
    idx = low.find(name_l.split()[0]) if name_l else -1
    if idx >= 0:
        snippet = instruction[max(0, idx - 20) : idx + 40].strip()
        snippet = re.sub(r"^\W+|\W+$", "", snippet)
        return snippet[:48] if snippet else "use"
    return "add"


def rule_based_etrn(recipe: Recipe) -> dict[str, Any]:
    """Build eTRN JSON + markdown table with simple keyword matching."""
    ingredients_raw = recipe.ingredients or []
    instructions = recipe.instructions or []

    if not ingredients_raw and recipe.raw_text:
        # Extreme fallback: treat non-empty lines as ingredients
        ingredients_raw = _clean_lines(recipe.raw_text)[:30]

    if not instructions:
        instructions = ["Combine and cook according to recipe.", "Serve."]

    # Cap stages for density (merge if many)
    stages_src = instructions[:12]
    if len(instructions) > 12:
        # Keep first 10 and last 2
        stages_src = instructions[:10] + instructions[-2:]

    ing_objs: list[dict[str, Any]] = []
    for i, raw in enumerate(ingredients_raw):
        name = _ingredient_name(raw)
        prep = ""
        if "," in raw:
            prep = raw.split(",", 1)[1].strip()
        ing_objs.append(
            {
                "id": f"i{i}",
                "qty_us": "",
                "qty_metric": "",
                "name": name,
                "prep": prep,
                "raw": raw,
            }
        )

    stages: list[dict[str, Any]] = []
    for si, inst in enumerate(stages_src):
        label = _stage_label(inst, si)
        actions: dict[str, str] = {}
        inst_tokens = _name_tokens(inst)
        for ing in ing_objs:
            name = ing["name"]
            tokens = _name_tokens(name)
            # Match if any significant token of ingredient appears in stage
            hit = bool(tokens & inst_tokens)
            if not hit:
                # partial: any token length>3 contained as substring
                low = inst.lower()
                hit = any(t in low for t in tokens if len(t) > 3)
            if not hit and si == 0 and not any(
                _name_tokens(ing2["name"]) & inst_tokens for ing2 in ing_objs
            ):
                # First stage with zero hits: leave empty (mise may cover prep)
                hit = False
            if hit:
                actions[ing["id"]] = _cell_action(inst, name)
        # If still no actions, attach a blanket note on first ingredient once
        if not actions and ing_objs:
            # Put stage-level action on a synthetic "— procedure —" only if truly empty
            pass
        duration = ""
        time_m = re.search(
            r"(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))",
            inst,
            re.I,
        )
        if time_m:
            duration = time_m.group(1)
        temp = None
        temp_m = re.search(r"(\d{2,3})\s*°\s*([FC])", inst, re.I)
        if temp_m:
            temp = f"{temp_m.group(1)}°{temp_m.group(2).upper()}"

        stages.append(
            {
                "id": f"st{si + 1}",
                "label": label,
                "duration": duration,
                "temp": temp,
                "equipment": [],
                "actions": actions,
                "produces": "",
            }
        )

    # Order ingredients by first stage appearance
    first_use: dict[str, int] = {}
    for si, st in enumerate(stages):
        for iid in st["actions"]:
            first_use.setdefault(iid, si)
    ing_objs.sort(key=lambda x: (first_use.get(x["id"], 999), x["id"]))

    # Mise-en-place: prep notes with no stage hit still listed as prep
    mise = []
    for ing in ing_objs:
        if ing["prep"] and ing["id"] not in first_use:
            mise.append({"item": ing["name"], "notes": ing["prep"]})
        elif ing["prep"]:
            mise.append({"item": ing["name"], "notes": f"prep: {ing['prep']}"})

    md = build_markdown_table(ing_objs, stages)

    return {
        "meta": {
            "title": recipe.title,
            "yield": recipe.yield_,
            "source": recipe.source,
            "total_times": {
                "active": "",
                "passive": "",
                "total": recipe.total_time or "",
            },
        },
        "equipment": [],
        "mise_en_place": mise,
        "ingredients": ing_objs,
        "stages": stages,
        "notes": [
            "Generated by TRN rule-based converter. Toggle LLM path for denser stage labels.",
        ],
        "markdown_table": md,
        "generator": {"path": "rule-based", "version": APP_VERSION},
    }


def build_markdown_table(
    ingredients: list[dict[str, Any]], stages: list[dict[str, Any]]
) -> str:
    headers = ["Ingredient"] + [s["label"] for s in stages]
    sep = ["---"] * len(headers)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for ing in ingredients:
        label = ing.get("raw") or ing.get("name") or ""
        # Prefer compact name + qty if raw is long
        if len(label) > 48:
            label = ing.get("name") or label[:48]
        cells = [label]
        for st in stages:
            cells.append(st.get("actions", {}).get(ing["id"], ""))
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


def llm_etrn(
    recipe: Recipe,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url.rstrip("/") or DEFAULT_BASE_URL)

    user_payload = {
        "title": recipe.title,
        "yield": recipe.yield_,
        "source": recipe.source,
        "total_time": recipe.total_time,
        "ingredients": recipe.ingredients,
        "instructions": recipe.instructions,
        "raw_text": recipe.raw_text[:8000] if recipe.raw_text else "",
    }
    resp = client.chat.completions.create(
        model=model or DEFAULT_MODEL,
        temperature=0.2,
        messages=[
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Convert this recipe to eTRN JSON only:\n\n"
                    + json.dumps(user_payload, ensure_ascii=False, indent=2)
                ),
            },
        ],
    )
    content = resp.choices[0].message.content or ""
    # Strip fences if model wraps
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    data = json.loads(content)
    if "markdown_table" not in data or not data["markdown_table"]:
        data["markdown_table"] = build_markdown_table(
            data.get("ingredients") or [], data.get("stages") or []
        )
    data["generator"] = {
        "path": "llm",
        "model": model,
        "base_url": base_url,
        "version": APP_VERSION,
    }
    # Fill meta source if empty
    meta = data.setdefault("meta", {})
    if not meta.get("title"):
        meta["title"] = recipe.title
    if not meta.get("source"):
        meta["source"] = recipe.source
    return data


# ---------------------------------------------------------------------------
# Printable HTML
# ---------------------------------------------------------------------------


def printable_html(etrn: dict[str, Any]) -> str:
    meta = etrn.get("meta") or {}
    title = meta.get("title") or "Recipe"
    yield_ = meta.get("yield") or ""
    source = meta.get("source") or ""
    times = meta.get("total_times") or {}
    md = etrn.get("markdown_table") or ""
    table_html = markdown_table_to_html(md)
    mise = etrn.get("mise_en_place") or []
    notes = etrn.get("notes") or []
    mise_html = ""
    if mise:
        items = "".join(
            f"<li><strong>{_esc(m.get('item', ''))}</strong>"
            f"{(' — ' + _esc(m.get('notes', ''))) if m.get('notes') else ''}</li>"
            for m in mise
            if m.get("item")
        )
        mise_html = f"<h2>Mise en place</h2><ul>{items}</ul>"
    notes_html = ""
    if notes:
        notes_html = "<h2>Notes</h2><ul>" + "".join(
            f"<li>{_esc(str(n))}</li>" for n in notes
        ) + "</ul>"

    sub = " · ".join(
        x
        for x in [
            f"Yield: {yield_}" if yield_ else "",
            f"Total: {times.get('total')}" if times.get("total") else "",
            f"Source: {source}" if source else "",
        ]
        if x
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>{_esc(title)} — eTRN</title>
<style>
  @page {{ margin: 12mm; }}
  body {{
    font-family: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
    color: #111; background: #fff; margin: 0; padding: 16px;
    font-size: 11pt; line-height: 1.35;
  }}
  h1 {{ font-size: 18pt; margin: 0 0 4px; }}
  .sub {{ color: #444; font-size: 9pt; margin-bottom: 14px; }}
  table.trn {{
    border-collapse: collapse; width: 100%; font-size: 9pt;
    font-family: "IBM Plex Mono", "JetBrains Mono", ui-monospace, monospace;
  }}
  table.trn th, table.trn td {{
    border: 1px solid #222; padding: 4px 6px; vertical-align: top;
  }}
  table.trn th {{
    background: #111; color: #fff; font-weight: 600; text-align: left;
  }}
  table.trn td:first-child, table.trn th:first-child {{
    font-weight: 600; white-space: nowrap; max-width: 14em;
  }}
  table.trn tr:nth-child(even) td {{ background: #f6f6f6; }}
  h2 {{ font-size: 12pt; margin: 16px 0 6px; }}
  ul {{ margin: 0 0 8px 1.2em; padding: 0; }}
  .howto {{ margin-top: 18px; font-size: 9pt; color: #333; }}
  @media print {{
    body {{ padding: 0; }}
    .noprint {{ display: none; }}
  }}
</style>
</head>
<body>
  <h1>{_esc(title)}</h1>
  <div class="sub">{_esc(sub)}</div>
  {table_html}
  {mise_html}
  {notes_html}
  <div class="howto">
    <strong>How to read this table.</strong>
    Rows are ingredients in first-use order.
    Columns are chronological process stages.
    A cell holds the short action for that ingredient in that stage; empty means idle.
    Read left → right across a row to follow one ingredient; read a column for one stage.
  </div>
</body>
</html>
"""


def _esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def markdown_table_to_html(md: str) -> str:
    lines = [ln.strip() for ln in md.strip().splitlines() if ln.strip()]
    if len(lines) < 2:
        return f"<pre>{_esc(md)}</pre>"
    rows = []
    for ln in lines:
        if re.match(r"^\|?\s*:?---", ln):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        rows.append(cells)
    if not rows:
        return f"<pre>{_esc(md)}</pre>"
    head = rows[0]
    body = rows[1:]
    th = "".join(f"<th>{_esc(c)}</th>" for c in head)
    trs = []
    for r in body:
        # pad
        while len(r) < len(head):
            r.append("")
        trs.append("<tr>" + "".join(f"<td>{_esc(c)}</td>" for c in r[: len(head)]) + "</tr>")
    return f'<table class="trn"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def streamlit_table_html(md: str) -> str:
    """Dark dense table for on-screen Streamlit render."""
    base = markdown_table_to_html(md)
    return f"""
<style>
  .trn-wrap {{ overflow-x: auto; margin: 0.5rem 0 1rem; }}
  .trn-wrap table.trn {{
    border-collapse: collapse; width: 100%;
    font-family: ui-monospace, "JetBrains Mono", Menlo, monospace;
    font-size: 0.82rem;
  }}
  .trn-wrap table.trn th, .trn-wrap table.trn td {{
    border: 1px solid #3a4638; padding: 0.35rem 0.5rem; vertical-align: top;
  }}
  .trn-wrap table.trn th {{
    background: #96f06a; color: #0a0b09; font-weight: 700; text-align: left;
  }}
  .trn-wrap table.trn td:first-child {{
    background: #161a14; color: #d7e8c8; font-weight: 600; white-space: nowrap;
  }}
  .trn-wrap table.trn tr:nth-child(even) td:not(:first-child) {{ background: #121510; }}
  .trn-wrap table.trn tr:nth-child(odd) td:not(:first-child) {{ background: #0e100d; }}
  .trn-wrap table.trn td {{ color: #c8d6bc; }}
</style>
<div class="trn-wrap">{base}</div>
"""


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(
        page_title="TRN — Tabular Recipe Notation",
        page_icon="▦",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.markdown(
        """
<style>
  .block-container { padding-top: 1.2rem; max-width: 1200px; }
  h1, h2, h3 { letter-spacing: -0.02em; }
  div[data-testid="stSidebar"] { background: #0a0b09; }
</style>
""",
        unsafe_allow_html=True,
    )

    with st.sidebar:
        st.markdown("### TRN")
        st.caption(f"v{APP_VERSION} · f00 · eTRN converter")
        st.markdown("---")
        use_llm = st.toggle("High-quality LLM path", value=False)
        api_key = ""
        model = DEFAULT_MODEL
        base_url = DEFAULT_BASE_URL
        if use_llm:
            api_key = st.text_input(
                "API key (xAI / OpenAI-compatible)",
                type="password",
                help="Never committed. Stored only in this browser session.",
            )
            base_url = st.text_input("base_url", value=DEFAULT_BASE_URL)
            model = st.text_input("model", value=DEFAULT_MODEL)
        st.markdown("---")
        st.markdown("**Install / run**")
        st.code(
            "pip install streamlit recipe-scrapers openai requests beautifulsoup4\n"
            "streamlit run app.py",
            language="bash",
        )
        st.markdown(
            "Live site: [trn.f00.sh](https://trn.f00.sh) · "
            "Repo: [f00-sh/trn](https://github.com/f00-sh/trn)"
        )
        st.markdown("---")
        st.caption(
            "Rule-based path works offline. LLM path needs a key and network. "
            "API keys never leave this session except to the base_url you set."
        )

    st.title("TRN")
    st.markdown(
        "Convert any recipe into **Enhanced Tabular Recipe Notation** — "
        "ingredient rows × chronological stages, dense like "
        "[Cooking for Engineers](https://www.cookingforengineers.com/)."
    )

    col_u, col_p = st.columns(2)
    with col_u:
        url = st.text_input("Recipe URL", placeholder="https://…")
    with col_p:
        st.caption("Paste is the reliable fallback when sites block scrapers.")

    paste = st.text_area(
        "Or paste full recipe text",
        height=220,
        placeholder="Title\n\nIngredients:\n- …\n\nInstructions:\n1. …",
    )

    convert = st.button("Convert", type="primary", use_container_width=False)

    if convert:
        recipe: Recipe | None = None
        err: str | None = None

        if url.strip():
            with st.spinner("Fetching recipe…"):
                recipe, err = scrape_url(url.strip())
            if err and not recipe:
                st.warning(err)
            if recipe is None and paste.strip():
                st.info("Falling back to pasted text.")
                recipe = parse_pasted_recipe(paste)
        elif paste.strip():
            recipe = parse_pasted_recipe(paste)
        else:
            st.error("Provide a recipe URL or paste recipe text.")
            return

        if recipe is None:
            return

        if not recipe.ingredients and not recipe.instructions:
            st.error(
                "Could not extract ingredients or instructions. "
                "Paste a clearer recipe (include Ingredients and Instructions headers)."
            )
            return

        st.success(
            f"**{recipe.title}** — "
            f"{len(recipe.ingredients)} ingredients · "
            f"{len(recipe.instructions)} steps"
            + (f" · {recipe.yield_}" if recipe.yield_ else "")
        )

        etrn: dict[str, Any]
        with st.spinner("Building eTRN matrix…"):
            if use_llm:
                if not api_key.strip():
                    st.error("LLM path requires an API key in the sidebar.")
                    return
                try:
                    etrn = llm_etrn(recipe, api_key.strip(), base_url.strip(), model.strip())
                except Exception as e:  # noqa: BLE001
                    st.error(f"LLM conversion failed: {e}")
                    st.info("Falling back to rule-based conversion.")
                    etrn = rule_based_etrn(recipe)
            else:
                etrn = rule_based_etrn(recipe)

        st.session_state["etrn"] = etrn
        st.session_state["recipe"] = {
            "title": recipe.title,
            "ingredients": recipe.ingredients,
            "instructions": recipe.instructions,
            "source": recipe.source,
        }

    etrn = st.session_state.get("etrn")
    if not etrn:
        st.markdown("---")
        st.markdown(
            """
#### How to read a TRN table
- **Rows** = ingredients, ordered by first use.
- **Columns** = chronological process stages (short labels).
- **Cells** = concise action for that ingredient in that stage (empty = idle).
- Read a **row** left→right to follow one ingredient; read a **column** for one stage.
"""
        )
        return

    meta = etrn.get("meta") or {}
    st.markdown("---")
    st.subheader(meta.get("title") or "eTRN table")
    path = (etrn.get("generator") or {}).get("path", "?")
    st.caption(f"Generator: {path}")

    md = etrn.get("markdown_table") or ""
    st.markdown(streamlit_table_html(md), unsafe_allow_html=True)

    # Also show raw markdown for copy
    with st.expander("Markdown table source"):
        st.code(md, language="markdown")

    col_j, col_print = st.columns(2)
    with col_j:
        with st.expander("Raw eTRN JSON", expanded=False):
            st.json(etrn)
            st.download_button(
                "Download eTRN JSON",
                data=json.dumps(etrn, indent=2, ensure_ascii=False),
                file_name=_safe_filename(meta.get("title") or "recipe") + ".etrn.json",
                mime="application/json",
            )
    with col_print:
        with st.expander("Printable view (Ctrl/Cmd+P → Save as PDF)", expanded=False):
            html = printable_html(etrn)
            st.download_button(
                "Download printable HTML",
                data=html,
                file_name=_safe_filename(meta.get("title") or "recipe") + ".trn.html",
                mime="text/html",
            )
            components.html(html, height=520, scrolling=True)

    st.markdown("---")
    st.markdown(
        """
### How to read this table
1. **Rows** are ingredients in first-use order (with quantities when known).
2. **Columns** are short chronological stages (`melt`, `cream`, `fold`, `bake 350°F 25min`).
3. A **cell** is the action for that ingredient in that stage; blank means it sits idle.
4. Follow one ingredient across a row, or read a full stage down a column.
5. Critical **temps**, **times**, and **until…** conditions stay in labels or cells.

TRN is a [f00](https://f00.sh) product. MIT licensed.
"""
    )


def _safe_filename(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", name.strip().lower()).strip("-")
    return (s or "recipe")[:80]


if __name__ == "__main__":
    main()
