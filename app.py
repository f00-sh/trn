#!/usr/bin/env python3
"""TRN — Cooking for Engineers–style Tabular Recipe Notation converter (Streamlit).

Accepts a recipe URL or pasted text, extracts title/ingredients/instructions,
and builds a CFE process matrix: ingredient rows × chronological process timeline
with rowspan-merged mixture groups.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

import streamlit as st
import streamlit.components.v1 as components

APP_VERSION = "0.1.1"
DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_MODEL = "grok-3"

LLM_SYSTEM_PROMPT = """You are an expert at converting traditional recipes into Tabular Recipe Notation (TRN) exactly like Cooking for Engineers (Michael Chu).

Output ONLY valid JSON with this structure:
{
"meta": {"title": "", "yield": "", "source": "", "total_times": {"active": "", "passive": "", "total": ""}, "banner": "optional top note e.g. Preheat oven to 375°F"},
"equipment": [],
"mise_en_place": [{"item": "", "notes": ""}],
"ingredients": [{"id": "i0", "qty_us": "", "qty_metric": "", "name": "", "prep": "", "raw": "1 cup (220 g) unsalted butter"}],
"stages": [
  {"id": "st1", "action": "soften", "members": ["i0"]},
  {"id": "st2", "action": "beat", "members": ["i0", "i1", "i2", "i3"]},
  {"id": "st3", "action": "beat in one egg at a time", "members": ["i0", "i1", "i2", "i3", "i4"]}
],
"notes": [],
"markdown_table": ""
}

CRITICAL Cooking-for-Engineers rules (match the classic recipe cards):
1. LEFT column = ingredients with quantities (prefer dual units when known). Order ingredients so mixture groups stay CONTIGUOUS.
2. Process columns (left→right) are a TIMELINE of operations — NOT a header row of stage names. There is NO "Stage1 | Stage2" header. The action TEXT lives in the cells.
3. When several ingredients are worked as one mixture, they form a vertical group. The action appears once on the FIRST ingredient of that group; other rows in the group are blank in that column (rowspan in HTML).
4. Parallel prep is allowed: e.g. dry ingredients "mix" in an early column while butter "soften"s in the same timeline column on a different group.
5. Later columns carry the main stream forward (beat → fold → bake…). Ingredients already in the bowl stay in the member set even if not re-named.
6. Action text is short and imperative like CFE: "soften", "beat", "beat in one egg at a time", "slowly beat in flour", "stir", "form into rough balls", "bake 375°F 10 min."
7. Preserve temps, times, and until-conditions in the action text.
8. Set markdown_table to a CFE-style markdown matrix: first column ingredient raw text; subsequent columns are process actions with blanks for non-head rows of a group. Optional banner only in meta.banner.
9. stages[].members lists ingredient ids in that process step (the rowspan group). stages[].action is the cell text.
"""

ACTION_KEYWORDS: list[tuple[str, list[str]]] = [
    ("prep", ["chop", "dice", "mince", "slice", "peel", "grate", "zest", "measure", "sift"]),
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
    # process nouns that false-positive against ingredient tokens
    "baking", "pan", "sheet", "bowl", "mixture", "dough", "batter", "heat",
    "oven", "minutes", "minute", "hour", "hours", "degree", "degrees",
}


@dataclass
class Recipe:
    title: str = "Untitled recipe"
    ingredients: list[str] = field(default_factory=list)
    instructions: list[str] = field(default_factory=list)
    yield_: str = ""
    source: str = ""
    total_time: str = ""
    raw_text: str = ""


def _esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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
    text = text.strip()
    if not text:
        return Recipe()
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
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return Recipe(raw_text=text)
        title = lines[0]
        body = lines[1:]
        chunks = re.split(r"\n\s*\n", text, maxsplit=2)
        if len(chunks) >= 3:
            ingredients = _clean_lines(chunks[1])
            instructions = _clean_lines(chunks[2])
            if not ingredients and not instructions:
                ingredients = body[: max(1, len(body) // 2)]
                instructions = body[len(ingredients) :]
        else:
            short = [ln for ln in body if len(ln) < 80]
            if len(short) >= 3:
                cut = max(1, len(body) // 2)
                ingredients = body[:cut]
                instructions = body[cut:]
            else:
                ingredients = body
                instructions = []
    return Recipe(title=title, ingredients=ingredients, instructions=instructions, raw_text=text)


def extract_jsonld_recipe(html: str, source: str = "") -> Recipe | None:
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
    url = url.strip()
    if not url:
        return None, "Empty URL."
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None, "URL must start with http:// or https://."
    try:
        from recipe_scrapers import scrape_html, scrape_me  # type: ignore

        scraper = None
        err_primary: str | None = None
        try:
            scraper = scrape_me(url)
        except Exception as e:  # noqa: BLE001
            err_primary = str(e)
            try:
                import requests

                resp = requests.get(
                    url,
                    timeout=20,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; TRN/0.1; +https://trn.f00.sh)"},
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
        pass
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
                "User-Agent": "Mozilla/5.0 (compatible; TRN/0.1; +https://trn.f00.sh)",
                "Accept": "text/html,application/xhtml+xml",
            },
        )
        if resp.status_code in (401, 403, 429):
            return (
                None,
                f"Site blocked scraping (HTTP {resp.status_code}). Paste the recipe text instead.",
            )
        resp.raise_for_status()
        html = resp.text
    except Exception as e:  # noqa: BLE001
        return None, f"Could not fetch URL: {e}. Paste the recipe text instead."
    recipe = extract_jsonld_recipe(html, source=url)
    if recipe and (recipe.ingredients or recipe.instructions):
        return recipe, None
    try:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        title_el = soup.find("h1")
        title = (
            title_el.get_text(strip=True)
            if title_el
            else (soup.title.string if soup.title else "Untitled recipe")
        )
        text = soup.get_text("\n", strip=True)
        parsed_r = parse_pasted_recipe(f"{title}\n\n{text[:12000]}")
        parsed_r.source = url
        if parsed_r.ingredients or parsed_r.instructions:
            return parsed_r, None
    except Exception as e:  # noqa: BLE001
        return None, f"Parse failed: {e}. Paste the recipe text instead."
    return (
        None,
        "No recipe found on that page (blocked, paywall, or non-recipe HTML). Paste the recipe text instead.",
    )


# --- CFE conversion ---------------------------------------------------------


def _ingredient_name(raw: str) -> str:
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
    s = re.sub(r"^(?:of\s+)+", "", s, flags=re.I)
    name = s.split(",")[0].strip()
    return re.sub(r"\s+", " ", name) or raw.strip()


def _name_tokens(name: str) -> set[str]:
    toks = re.findall(r"[a-zA-Z][a-zA-Z\-']+", name.lower())
    out: set[str] = set()
    for t in toks:
        if t in STOPWORDS or len(t) <= 2:
            continue
        out.add(t)
        if t.endswith("es") and len(t) > 4:
            out.add(t[:-2])
        elif t.endswith("s") and len(t) > 3:
            out.add(t[:-1])
        else:
            out.add(t + "s")
    return out


def _match_ingredients(instruction: str, ing_objs: list[dict[str, Any]]) -> list[str]:
    low = instruction.lower()
    inst_tokens = _name_tokens(instruction)
    hits: list[str] = []
    for ing in ing_objs:
        tokens = _name_tokens(ing["name"])
        if tokens & inst_tokens:
            hits.append(ing["id"])
            continue
        # substring fallback for multi-word names
        for t in tokens:
            if len(t) > 3 and re.search(rf"(?<![a-z]){re.escape(t)}(?![a-z])", low):
                hits.append(ing["id"])
                break
    return hits


def _process_action(instruction: str, index: int) -> str:
    text = re.sub(r"^\d+[\.\)]\s*", "", instruction.strip())
    low = text.lower()
    temp = re.search(r"(\d{2,3})\s*°\s*([FC])", text, re.I)
    time_m = re.search(
        r"(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))", text, re.I
    )

    def _time() -> str:
        if not time_m:
            return ""
        t = re.sub(r"\s+", " ", time_m.group(1).strip())
        t = re.sub(r"minutes?|mins?", "min", t, flags=re.I)
        t = re.sub(r"hours?|hrs?", "hr", t, flags=re.I)
        return t

    if re.search(r"\bpreheat\b", low):
        if temp:
            return f"preheat {temp.group(1)}°{temp.group(2).upper()}"
        return "preheat oven"
    if re.search(r"\bsoften\b", low):
        return "soften"
    if re.search(r"\bcream\b", low):
        return "cream"
    # egg beat before generic flour/mix
    if re.search(r"\beggs?\b", low) and re.search(r"\b(beat|whisk|add)\b", low):
        if re.search(r"\bone\b|\bat a time\b", low):
            return "beat in one egg at a time"
        return "beat in eggs"
    # dry mix / set aside — plain "mix"
    if re.search(r"\bset aside\b|\bin a (?:separate |small )?bowl\b", low) and re.search(
        r"\b(mix|combine|whisk)\b", low
    ):
        return "mix"
    # incorporate flour into wet
    if re.search(r"\bflour\b", low) and re.search(
        r"\b(beat in|stir in|fold in|add.*flour|flour mixture)\b", low
    ):
        return (
            "slowly beat in flour"
            if re.search(r"\bslow|little at a time|gradually\b", low)
            else "beat in flour"
        )
    if re.search(r"\b(form|scoop|drop|shape|portion)\b", low):
        return (
            "form into rough balls on a baking pan"
            if re.search(r"\b(ball|cookie|dough)\b", low)
            else "form and arrange"
        )
    if re.search(r"\b(bake|roast)\b", low):
        verb = "bake" if "bake" in low else "roast"
        bits = [verb]
        if temp:
            bits = [f"{verb} {temp.group(1)}°{temp.group(2).upper()}"]
        if _time():
            bits.append(_time())
        return " ".join(bits)
    # Prefer specific verbs over the generic "mix" bucket
    for verb in (
        "beat",
        "whisk",
        "fold",
        "stir",
        "cream",
        "melt",
        "simmer",
        "boil",
        "saute",
        "sauté",
        "brown",
        "sear",
        "chill",
        "cool",
        "serve",
        "mix",
        "combine",
        "blend",
    ):
        if re.search(rf"(?<![a-z]){re.escape(verb)}(?![a-z])", low):
            return "saute" if verb in ("sauté", "brown", "sear") else verb
    for label, kws in ACTION_KEYWORDS:
        for kw in kws:
            if re.search(rf"(?<![a-z]){re.escape(kw)}(?![a-z])", low):
                if label in ("simmer", "bake") and (temp or _time()):
                    bits = [label]
                    if temp:
                        bits = [f"{label} {temp.group(1)}°{temp.group(2).upper()}"]
                    if _time():
                        bits.append(_time())
                    return " ".join(bits)
                return label
    words = re.findall(r"[A-Za-z0-9°/.\-]+", text)
    if not words:
        return f"step {index + 1}"
    phrase = " ".join(words[:8])
    if len(phrase) > 42:
        phrase = phrase[:40].rstrip() + "…"
    return phrase[0].lower() + phrase[1:]


def _extract_banner(instructions: list[str]) -> tuple[str, list[str]]:
    banner_parts: list[str] = []
    rest: list[str] = []
    for inst in instructions:
        low = inst.lower()
        if re.search(r"\bpreheat\b", low):
            banner_parts.append(re.sub(r"^\d+[\.\)]\s*", "", inst).strip())
        else:
            rest.append(inst)
    return ("; ".join(banner_parts), rest if rest else instructions)


def rule_based_etrn(recipe: Recipe) -> dict[str, Any]:
    ingredients_raw = recipe.ingredients or []
    instructions = list(recipe.instructions or [])
    if not ingredients_raw and recipe.raw_text:
        ingredients_raw = _clean_lines(recipe.raw_text)[:30]
    if not instructions:
        instructions = ["Combine and cook according to recipe.", "Serve."]
    banner, instructions = _extract_banner(instructions)
    if len(instructions) > 12:
        instructions = instructions[:10] + instructions[-2:]

    ing_objs: list[dict[str, Any]] = []
    for i, raw in enumerate(ingredients_raw):
        name = _ingredient_name(raw)
        prep = raw.split(",", 1)[1].strip() if "," in raw else ""
        ing_objs.append(
            {"id": f"i{i}", "qty_us": "", "qty_metric": "", "name": name, "prep": prep, "raw": raw}
        )

    main_mixture: list[str] = []
    stages: list[dict[str, Any]] = []
    first_use: dict[str, int] = {}

    for si, inst in enumerate(instructions):
        action = _process_action(inst, si)
        hits = _match_ingredients(inst, ing_objs)
        low = inst.lower()
        is_side = bool(
            re.search(r"\bin a (?:separate |small )?bowl\b|\bset aside\b|\breserve\b", low)
        ) or (
            hits
            and main_mixture
            and not any(h in main_mixture for h in hits)
            and re.search(r"\bmix\b|\bcombine\b|\bwhisk\b", low)
            and not re.search(r"\badd\b|\bfold\b|\bbeat in\b|\bstir in\b", low)
        )
        # Form/bake/serve with no real ingredient names → whole main mixture
        stream_only = bool(
            re.search(
                r"\b(form|shape|scoop|drop|portion|bake|roast|serve|plate|cool|chill|rest)\b",
                low,
            )
        )
        if hits and not (stream_only and not re.search(
            r"\b(butter|sugar|flour|egg|salt|oil|milk|cream|cheese|onion|garlic|chicken|beef|pork|fish)\b",
            low,
        )):
            members = list(hits)
            if not is_side and main_mixture:
                if re.search(r"\badd\b|\bfold\b|\bbeat in\b|\bstir in\b|\bcombine\b", low) or any(
                    h in main_mixture for h in hits
                ):
                    merged: list[str] = []
                    for iid in main_mixture + hits:
                        if iid not in merged:
                            merged.append(iid)
                    members = merged
            if not is_side:
                for iid in members:
                    if iid not in main_mixture:
                        main_mixture.append(iid)
        else:
            members = list(main_mixture) if main_mixture else ([ing_objs[0]["id"]] if ing_objs else [])
        for iid in members:
            first_use.setdefault(iid, si)
        duration = ""
        time_m = re.search(r"(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))", inst, re.I)
        if time_m:
            duration = time_m.group(1)
        temp = None
        temp_m = re.search(r"(\d{2,3})\s*°\s*([FC])", inst, re.I)
        if temp_m:
            temp = f"{temp_m.group(1)}°{temp_m.group(2).upper()}"
        stages.append(
            {
                "id": f"st{si + 1}",
                "action": action,
                "label": action,
                "members": members,
                "duration": duration,
                "temp": temp,
                "equipment": [],
                "actions": {iid: action for iid in members},
                "produces": "",
            }
        )

    order_index = {ing["id"]: i for i, ing in enumerate(ing_objs)}
    ing_objs.sort(key=lambda x: (first_use.get(x["id"], 999), order_index[x["id"]]))
    id_order = {ing["id"]: i for i, ing in enumerate(ing_objs)}
    for st in stages:
        st["members"] = sorted(st.get("members") or [], key=lambda i: id_order.get(i, 999))

    mise = [{"item": ing["name"], "notes": f"prep: {ing['prep']}"} for ing in ing_objs if ing["prep"]]
    md = build_markdown_table(ing_objs, stages, banner=banner)
    html = render_cfe_html(ing_objs, stages, banner=banner, dark=False)
    return {
        "meta": {
            "title": recipe.title,
            "yield": recipe.yield_,
            "source": recipe.source,
            "banner": banner,
            "total_times": {"active": "", "passive": "", "total": recipe.total_time or ""},
        },
        "equipment": [],
        "mise_en_place": mise,
        "ingredients": ing_objs,
        "stages": stages,
        "notes": [
            "Cooking for Engineers–style TRN: left = ingredients; right = process timeline; "
            "blank cells under an action share that mixture (rowspan)."
        ],
        "markdown_table": md,
        "html_table": html,
        "generator": {"path": "rule-based", "version": APP_VERSION, "format": "cfe-trn"},
    }


def build_markdown_table(
    ingredients: list[dict[str, Any]], stages: list[dict[str, Any]], banner: str = ""
) -> str:
    n = len(stages)
    lines: list[str] = []
    if banner:
        lines.append("| " + " | ".join([banner.replace("|", "/")] + [""] * n) + " |")
    lines.append("| " + " | ".join(["---"] * (n + 1)) + " |")
    id_to_row = {ing["id"]: ri for ri, ing in enumerate(ingredients)}
    for ri, ing in enumerate(ingredients):
        label = ing.get("raw") or ing.get("name") or ""
        if len(label) > 56:
            label = (ing.get("name") or label)[:56]
        cells = [label]
        for st in stages:
            members = st.get("members") or list((st.get("actions") or {}).keys())
            action = st.get("action") or st.get("label") or ""
            if ing["id"] not in members:
                cells.append("")
                continue
            member_rows = sorted(id_to_row[m] for m in members if m in id_to_row)
            run_start = ri
            while run_start - 1 in member_rows:
                run_start -= 1
            cells.append(action if ri == run_start else "")
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return "\n".join(lines)


def render_cfe_html(
    ingredients: list[dict[str, Any]],
    stages: list[dict[str, Any]],
    banner: str = "",
    dark: bool = True,
) -> str:
    id_to_row = {ing["id"]: ri for ri, ing in enumerate(ingredients)}
    n_rows = len(ingredients)
    n_cols = len(stages)
    skip = [[False] * n_cols for _ in range(n_rows)]
    rowspan_at: dict[tuple[int, int], int] = {}
    text_at: dict[tuple[int, int], str] = {}
    for ci, st in enumerate(stages):
        members = st.get("members") or list((st.get("actions") or {}).keys())
        action = st.get("action") or st.get("label") or ""
        member_rows = sorted({id_to_row[m] for m in members if m in id_to_row})
        run: list[int] = []

        def flush(run_rows: list[int]) -> None:
            if not run_rows:
                return
            head = run_rows[0]
            text_at[(head, ci)] = action
            rowspan_at[(head, ci)] = len(run_rows)
            for r in run_rows[1:]:
                skip[r][ci] = True

        for r in member_rows:
            if run and r != run[-1] + 1:
                flush(run)
                run = [r]
            else:
                run.append(r)
        flush(run)

    cls = "trn cfe dark" if dark else "trn cfe"
    parts = [f'<table class="{cls}">']
    if banner:
        parts.append(
            f'<tr class="banner"><td class="ing banner-ing"></td>'
            f'<td class="banner-cell" colspan="{max(n_cols, 1)}">{_esc(banner)}</td></tr>'
        )
    for ri, ing in enumerate(ingredients):
        label = ing.get("raw") or ing.get("name") or ""
        parts.append("<tr>")
        parts.append(f'<td class="ing">{_esc(label)}</td>')
        for ci in range(n_cols):
            if skip[ri][ci]:
                continue
            span = rowspan_at.get((ri, ci), 1)
            txt = text_at.get((ri, ci), "")
            rs = f' rowspan="{span}"' if span > 1 else ""
            cell_cls = "act" if txt else "empty"
            parts.append(f'<td class="{cell_cls}"{rs}>{_esc(txt)}</td>')
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)


def llm_etrn(recipe: Recipe, api_key: str, base_url: str, model: str) -> dict[str, Any]:
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
                "content": "Convert this recipe to Cooking-for-Engineers TRN JSON only:\n\n"
                + json.dumps(user_payload, ensure_ascii=False, indent=2),
            },
        ],
    )
    content = (resp.choices[0].message.content or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)
    data = json.loads(content)
    ings = data.get("ingredients") or []
    stages = data.get("stages") or []
    for st in stages:
        if "action" not in st and "label" in st:
            st["action"] = st["label"]
        if "members" not in st:
            acts = st.get("actions") or {}
            st["members"] = list(acts.keys()) if acts else []
        st.setdefault("label", st.get("action", ""))
    banner = (data.get("meta") or {}).get("banner") or ""
    data["markdown_table"] = build_markdown_table(ings, stages, banner=banner)
    data["html_table"] = render_cfe_html(ings, stages, banner=banner, dark=False)
    data["generator"] = {
        "path": "llm",
        "model": model,
        "base_url": base_url,
        "version": APP_VERSION,
        "format": "cfe-trn",
    }
    meta = data.setdefault("meta", {})
    if not meta.get("title"):
        meta["title"] = recipe.title
    if not meta.get("source"):
        meta["source"] = recipe.source
    return data


def printable_html(etrn: dict[str, Any]) -> str:
    meta = etrn.get("meta") or {}
    title = meta.get("title") or "Recipe"
    yield_ = meta.get("yield") or ""
    source = meta.get("source") or ""
    times = meta.get("total_times") or {}
    banner = meta.get("banner") or ""
    ings = etrn.get("ingredients") or []
    stages = etrn.get("stages") or []
    table_html = etrn.get("html_table") or render_cfe_html(ings, stages, banner=banner, dark=False)
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
        notes_html = "<h2>Notes</h2><ul>" + "".join(f"<li>{_esc(str(n))}</li>" for n in notes) + "</ul>"
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
<html lang="en"><head><meta charset="utf-8"/><title>{_esc(title)} — TRN</title>
<style>
@page{{margin:12mm}}
body{{font-family:system-ui,sans-serif;color:#111;background:#fff;margin:0;padding:16px;font-size:11pt;line-height:1.35}}
h1{{font-size:18pt;margin:0 0 4px}}
.sub{{color:#444;font-size:9pt;margin-bottom:14px}}
table.trn{{border-collapse:collapse;width:100%;font-size:9pt;font-family:ui-monospace,monospace}}
table.trn td{{border:1px solid #222;padding:5px 7px;vertical-align:middle}}
table.trn td.ing{{font-weight:600;white-space:nowrap;background:#f4f4f4;text-align:left;max-width:16em}}
table.trn td.act{{text-align:center;font-weight:600;background:#fff}}
table.trn td.empty{{background:#fff}}
table.trn tr.banner td{{background:#111;color:#fff;font-weight:600;text-align:left}}
table.trn tr.banner td.banner-ing{{background:#111;width:0;padding:0;border-right:0}}
h2{{font-size:12pt;margin:16px 0 6px}}
ul{{margin:0 0 8px 1.2em;padding:0}}
.howto{{margin-top:18px;font-size:9pt;color:#333}}
@media print{{body{{padding:0}}}}
</style></head><body>
<h1>{_esc(title)}</h1>
<div class="sub">{_esc(sub)}</div>
{table_html}
{mise_html}
{notes_html}
<div class="howto"><strong>How to read this table (Cooking for Engineers TRN).</strong>
Left column = ingredients with quantities.
Columns to the right = process timeline (read left → right).
An action that spans several rows means those ingredients are one mixture.
Blank cells under an action are still in that mixture.
Separate filled cells in the same column are parallel work.</div>
</body></html>"""


def streamlit_table_html(etrn: dict[str, Any]) -> str:
    meta = etrn.get("meta") or {}
    banner = meta.get("banner") or ""
    ings = etrn.get("ingredients") or []
    stages = etrn.get("stages") or []
    table = etrn.get("html_table") or render_cfe_html(ings, stages, banner=banner, dark=True)
    table = table.replace('class="trn cfe"', 'class="trn cfe dark"')
    return f"""
<style>
  .trn-wrap {{ overflow-x: auto; margin: 0.5rem 0 1rem; }}
  .trn-wrap table.trn {{
    border-collapse: collapse; width: 100%;
    font-family: ui-monospace, "JetBrains Mono", Menlo, monospace;
    font-size: 0.82rem;
  }}
  .trn-wrap table.trn td {{
    border: 1px solid #3a4638; padding: 0.4rem 0.55rem; vertical-align: middle;
  }}
  .trn-wrap table.trn td.ing {{
    background: #161a14; color: #d7e8c8; font-weight: 600; white-space: nowrap;
    text-align: left; max-width: 16em;
  }}
  .trn-wrap table.trn td.act {{
    background: #0e100d; color: #96f06a; font-weight: 600; text-align: center;
  }}
  .trn-wrap table.trn td.empty {{ background: #0a0b09; }}
  .trn-wrap table.trn tr.banner td {{
    background: #96f06a; color: #0a0b09; font-weight: 700; text-align: left;
  }}
  .trn-wrap table.trn tr.banner td.banner-ing {{
    background: #96f06a; border-right: none; width: 0; padding: 0;
  }}
</style>
<div class="trn-wrap">{table}</div>
"""


def _safe_filename(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", name.strip().lower()).strip("-")
    return (s or "recipe")[:80]


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
        st.caption(f"v{APP_VERSION} · f00 · Cooking for Engineers–style")
        st.markdown("---")
        use_llm = st.toggle("High-quality LLM path", value=False)
        api_key = ""
        model = DEFAULT_MODEL
        base_url = DEFAULT_BASE_URL
        if use_llm:
            api_key = st.text_input("API key (xAI / OpenAI-compatible)", type="password")
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
        st.caption(
            "Rule-based path works offline. LLM path needs a key. "
            "Format matches Cooking for Engineers recipe cards."
        )

    st.title("TRN")
    st.markdown(
        "Convert any recipe into **Tabular Recipe Notation** — "
        "the [Cooking for Engineers](https://www.cookingforengineers.com/) process matrix: "
        "ingredient column + process timeline with mixture groups."
    )
    col_u, _ = st.columns(2)
    with col_u:
        url = st.text_input("Recipe URL", placeholder="https://…")
    paste = st.text_area(
        "Or paste full recipe text",
        height=220,
        placeholder="Title\n\nIngredients:\n- …\n\nInstructions:\n1. …",
    )
    convert = st.button("Convert", type="primary")

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
            f"**{recipe.title}** — {len(recipe.ingredients)} ingredients · "
            f"{len(recipe.instructions)} steps"
            + (f" · {recipe.yield_}" if recipe.yield_ else "")
        )
        with st.spinner("Building CFE process matrix…"):
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

    etrn = st.session_state.get("etrn")
    if not etrn:
        st.markdown("---")
        st.markdown(
            """
#### How to read a Cooking for Engineers TRN table
- **Left column** = ingredients with quantities (grouped by mixture).
- **Columns to the right** = process **timeline** (left → right). No stage header row.
- An **action cell that spans several rows** means those ingredients are one mixture.
- **Blank cells** under an action are still in that mixture.
- **Parallel work** shows as separate filled cells in the same column (e.g. dry *mix* while butter *soften*s).
"""
        )
        return

    meta = etrn.get("meta") or {}
    st.markdown("---")
    st.subheader(meta.get("title") or "TRN table")
    path = (etrn.get("generator") or {}).get("path", "?")
    st.caption(f"Generator: {path} · format: cfe-trn")
    st.markdown(streamlit_table_html(etrn), unsafe_allow_html=True)

    with st.expander("Markdown table source"):
        st.code(etrn.get("markdown_table") or "", language="markdown")
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
1. **Left** = shopping list / mise (quantities on the ingredient).
2. **Rightward columns** = chronological process timeline.
3. **Rowspan action** = those ingredients are handled together.
4. **Empty under an action** = still in that mixture.
5. **Two actions in one column** = parallel tracks.

TRN is a [f00](https://f00.sh) product. MIT licensed. Inspired by Cooking for Engineers.
"""
    )


if __name__ == "__main__":
    main()
