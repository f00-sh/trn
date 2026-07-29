/* TRN site — Cooking for Engineers–style process matrix */
(() => {
  "use strict";

  const APP_VERSION = "0.1.1";
  const DEFAULT_BASE_URL = "https://api.x.ai/v1";
  const DEFAULT_MODEL = "grok-3";

  const LLM_SYSTEM_PROMPT = `You are an expert at converting traditional recipes into Tabular Recipe Notation (TRN) exactly like Cooking for Engineers (Michael Chu).
Output ONLY valid JSON with this structure:
{
"meta": {"title": "", "yield": "", "source": "", "total_times": {"active": "", "passive": "", "total": ""}, "banner": "optional top note e.g. Preheat oven to 375°F"},
"equipment": [],
"mise_en_place": [{"item": "", "notes": ""}],
"ingredients": [{"id": "i0", "qty_us": "", "qty_metric": "", "name": "", "prep": "", "raw": "1 cup (220 g) unsalted butter"}],
"stages": [
  {"id": "st1", "action": "soften", "members": ["i0"]},
  {"id": "st2", "action": "beat", "members": ["i0", "i1", "i2", "i3"]}
],
"notes": [],
"markdown_table": ""
}
CRITICAL: LEFT column = ingredients with quantities, contiguous mixture groups.
Process columns are a TIMELINE (no stage header row). Action text lives in cells.
Multi-ingredient steps: action on first row of group; siblings blank (rowspan).
Parallel prep allowed in the same column. stages[].members = ingredient ids; stages[].action = cell text.
Preserve temps/times/until conditions. Short CFE-style imperatives.`;

  const STOPWORDS = new Set([
    "a","an","the","and","or","of","to","in","into","with","for","on","until","about",
    "over","under","by","from","as","at","is","are","be","cup","cups","tbsp","tsp",
    "tablespoon","teaspoon","tablespoons","teaspoons","ounce","ounces","oz","lb","lbs",
    "pound","pounds","g","kg","ml","l","optional","plus","more","baking","pan","sheet",
    "bowl","mixture","dough","batter","heat","oven","minutes","minute","hour","hours",
  ]);

  const $ = (id) => document.getElementById(id);
  const llmToggle = $("llm-toggle");
  const llmSettings = $("llm-settings");
  const convertBtn = $("convert-btn");
  const statusEl = $("status");
  const results = $("results");
  let lastEtrn = null;

  function setStatus(msg, kind) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.classList.remove("err", "ok");
    if (kind) statusEl.classList.add(kind);
  }

  if (convertBtn && statusEl && results) {
    if (llmToggle && llmSettings) {
      llmToggle.addEventListener("change", () => {
        llmSettings.hidden = !llmToggle.checked;
      });
    }
    convertBtn.addEventListener("click", (ev) => {
      ev.preventDefault();
      onConvert();
    });
    const dlJson = $("dl-json");
    const dlHtml = $("dl-html");
    const printBtn = $("print-btn");
    if (dlJson) dlJson.addEventListener("click", () => downloadJson());
    if (dlHtml) dlHtml.addEventListener("click", () => downloadHtml());
    if (printBtn) {
      printBtn.addEventListener("click", () => {
        const frame = $("print-frame");
        if (frame && frame.contentWindow) frame.contentWindow.print();
      });
    }
  } else {
    console.error("TRN: missing required DOM nodes");
  }

  function cleanLines(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map((l) =>
        l
          .trim()
          .replace(/^[\-\*\u2022]+\s+/, "")
          .replace(/^\d+[\.\)]\s+/, "")
          .trim()
      )
      .filter(Boolean);
  }

  function parsePasted(text) {
    text = text.trim();
    if (!text) return null;
    const ingM = text.match(/^(ingredients?)\s*:?\s*$/im);
    const instM = text.match(
      /^(instructions?|directions?|method|steps?|preparation)\s*:?\s*$/im
    );
    let title = "Untitled recipe";
    let ingredients = [];
    let instructions = [];
    if (ingM && instM && ingM.index < instM.index) {
      const head = text.slice(0, ingM.index).trim();
      if (head) title = head.split(/\r?\n/)[0].trim() || title;
      ingredients = cleanLines(text.slice(ingM.index + ingM[0].length, instM.index));
      const instBlock = text.slice(instM.index + instM[0].length);
      const numbered = [
        ...instBlock.matchAll(
          /(?:^|\n)\s*(?:\d+[\.\)]\s+|step\s+\d+[:\.]?\s+)([^\n]+)/gi
        ),
      ].map((m) => m[1].trim());
      if (numbered.length) instructions = numbered;
      else {
        instructions = cleanLines(instBlock);
        if (instructions.length <= 1 && instBlock.trim()) {
          instructions = instBlock
            .split(/(?<=[.!?])\s+(?=[A-Z])/)
            .map((s) => s.trim())
            .filter(Boolean);
        }
      }
    } else {
      const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
      title = lines[0] || title;
      const chunks = text.split(/\n\s*\n/);
      if (chunks.length >= 3) {
        ingredients = cleanLines(chunks[1]);
        instructions = cleanLines(chunks.slice(2).join("\n\n"));
      } else {
        const body = lines.slice(1);
        const cut = Math.max(1, Math.floor(body.length / 2));
        ingredients = body.slice(0, cut);
        instructions = body.slice(cut);
      }
    }
    return {
      title,
      ingredients,
      instructions,
      yield: "",
      source: "",
      total_time: "",
      raw_text: text,
    };
  }

  async function scrapeUrl(url) {
    let res;
    try {
      res = await fetch("/api/scrape", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url }),
      });
    } catch (e) {
      throw new Error(
        `Network error talking to /api/scrape: ${e.message || e}. Paste the recipe instead.`
      );
    }
    const raw = await res.text();
    let data = {};
    try {
      data = raw ? JSON.parse(raw) : {};
    } catch {
      data = {};
    }
    if (!res.ok) {
      throw new Error(
        data.error || `Scrape failed (HTTP ${res.status}). Paste the recipe text instead.`
      );
    }
    if (!data.recipe) {
      throw new Error(data.error || "Scrape returned no recipe. Paste the text instead.");
    }
    return data.recipe;
  }

  function normalizeRecipe(recipe) {
    if (!recipe) return null;
    let out = { ...recipe };
    const hasParts =
      (out.ingredients && out.ingredients.length) ||
      (out.instructions && out.instructions.length);
    if (!hasParts && out.raw_text) {
      const parsed = parsePasted(out.raw_text);
      if (parsed) {
        out = {
          ...parsed,
          title: out.title || parsed.title,
          source: out.source || "",
          yield: out.yield || "",
          total_time: out.total_time || "",
        };
      }
    }
    return out;
  }

  function ingredientName(raw) {
    let s = raw.trim();
    s = s.replace(
      /^(?:about\s+|approx\.?\s+|approximately\s+)?[\d\s\/\.¼½¾⅓⅔⅛⅜⅝⅞\-]+(?:\s*(?:cups?|cup|tbsp|tsp|tablespoons?|teaspoons?|oz|ounces?|lbs?|pounds?|g|kg|ml|l|cloves?|cans?|packages?|pkgs?|sticks?|slices?|pinch(?:es)?|dash(?:es)?|whole))?\s+/i,
      ""
    );
    s = s.replace(/^(?:of\s+)+/i, "");
    const name = s.split(",")[0].trim().replace(/\s+/g, " ");
    return name || raw.trim();
  }

  function nameTokens(name) {
    const toks = (name.toLowerCase().match(/[a-zA-Z][a-zA-Z\-']+/g) || []);
    const out = new Set();
    for (const t of toks) {
      if (STOPWORDS.has(t) || t.length <= 2) continue;
      out.add(t);
      if (t.endsWith("es") && t.length > 4) out.add(t.slice(0, -2));
      else if (t.endsWith("s") && t.length > 3) out.add(t.slice(0, -1));
      else out.add(t + "s");
    }
    return out;
  }

  function matchIngredients(instruction, ingObjs) {
    const low = instruction.toLowerCase();
    const instTokens = nameTokens(instruction);
    const hits = [];
    for (const ing of ingObjs) {
      const tokens = nameTokens(ing.name);
      let hit = false;
      for (const t of tokens) {
        if (instTokens.has(t)) {
          hit = true;
          break;
        }
      }
      if (!hit) {
        for (const t of tokens) {
          if (t.length > 3 && new RegExp(`(?:^|[^a-z])${t}(?:$|[^a-z])`, "i").test(low)) {
            hit = true;
            break;
          }
        }
      }
      if (hit) hits.push(ing.id);
    }
    return hits;
  }

  function processAction(instruction, index) {
    let text = instruction.trim().replace(/^\d+[\.\)]\s*/, "");
    const low = text.toLowerCase();
    const temp = text.match(/(\d{2,3})\s*°\s*([FC])/i);
    const timeM = text.match(
      /(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))/i
    );
    const time = () => {
      if (!timeM) return "";
      return timeM[1]
        .replace(/\s+/g, " ")
        .replace(/minutes?|mins?/i, "min")
        .replace(/hours?|hrs?/i, "hr");
    };
    if (/\bpreheat\b/.test(low)) {
      return temp ? `preheat ${temp[1]}°${temp[2].toUpperCase()}` : "preheat oven";
    }
    if (/\bsoften\b/.test(low)) return "soften";
    if (/\bcream\b/.test(low)) return "cream";
    if (/\beggs?\b/.test(low) && /\b(beat|whisk|add)\b/.test(low)) {
      return /\bone\b|\bat a time\b/.test(low)
        ? "beat in one egg at a time"
        : "beat in eggs";
    }
    if (
      /\bset aside\b|\bin a (?:separate |small )?bowl\b/.test(low) &&
      /\b(mix|combine|whisk)\b/.test(low)
    ) {
      return "mix";
    }
    if (
      /\bflour\b/.test(low) &&
      /\b(beat in|stir in|fold in|add.*flour|flour mixture)\b/.test(low)
    ) {
      return /\bslow|little at a time|gradually\b/.test(low)
        ? "slowly beat in flour"
        : "beat in flour";
    }
    if (/\b(form|scoop|drop|shape|portion)\b/.test(low)) {
      return /\b(ball|cookie|dough)\b/.test(low)
        ? "form into rough balls on a baking pan"
        : "form and arrange";
    }
    if (/\b(bake|roast)\b/.test(low)) {
      const verb = /\bbake\b/.test(low) ? "bake" : "roast";
      let bits = [verb];
      if (temp) bits = [`${verb} ${temp[1]}°${temp[2].toUpperCase()}`];
      if (time()) bits.push(time());
      return bits.join(" ");
    }
    for (const verb of [
      "beat","whisk","fold","stir","cream","melt","simmer","boil","saute","sauté",
      "brown","sear","chill","cool","serve","mix","combine","blend",
    ]) {
      if (new RegExp(`(?:^|[^a-z])${verb}(?:$|[^a-z])`, "i").test(low)) {
        return verb === "sauté" || verb === "brown" || verb === "sear" ? "saute" : verb;
      }
    }
    const words = text.match(/[A-Za-z0-9°/.\-]+/g) || [];
    if (!words.length) return `step ${index + 1}`;
    let phrase = words.slice(0, 8).join(" ");
    if (phrase.length > 42) phrase = phrase.slice(0, 40).replace(/\s+\S*$/, "") + "…";
    return phrase.charAt(0).toLowerCase() + phrase.slice(1);
  }

  function extractBanner(instructions) {
    const banner = [];
    const rest = [];
    for (const inst of instructions) {
      if (/\bpreheat\b/i.test(inst)) banner.push(inst.replace(/^\d+[\.\)]\s*/, "").trim());
      else rest.push(inst);
    }
    return [banner.join("; "), rest.length ? rest : instructions];
  }

  function buildMarkdownTable(ingredients, stages, banner) {
    const n = stages.length;
    const lines = [];
    if (banner) {
      lines.push("| " + [banner, ...Array(n).fill("")].join(" | ") + " |");
    }
    lines.push("| " + Array(n + 1).fill("---").join(" | ") + " |");
    const idToRow = Object.fromEntries(ingredients.map((ing, ri) => [ing.id, ri]));
    ingredients.forEach((ing, ri) => {
      let label = ing.raw || ing.name || "";
      if (label.length > 56) label = (ing.name || label).slice(0, 56);
      const cells = [label];
      for (const st of stages) {
        const members = st.members || Object.keys(st.actions || {});
        const action = st.action || st.label || "";
        if (!members.includes(ing.id)) {
          cells.push("");
          continue;
        }
        const memberRows = members
          .filter((m) => idToRow[m] !== undefined)
          .map((m) => idToRow[m])
          .sort((a, b) => a - b);
        let runStart = ri;
        while (memberRows.includes(runStart - 1)) runStart--;
        cells.push(ri === runStart ? action : "");
      }
      lines.push(
        "| " + cells.map((c) => String(c).replace(/\|/g, "/")).join(" | ") + " |"
      );
    });
    return lines.join("\n");
  }

  function renderCfeHtml(ingredients, stages, banner, dark) {
    const idToRow = Object.fromEntries(ingredients.map((ing, ri) => [ing.id, ri]));
    const nRows = ingredients.length;
    const nCols = stages.length;
    const skip = Array.from({ length: nRows }, () => Array(nCols).fill(false));
    const rowspanAt = {};
    const textAt = {};
    stages.forEach((st, ci) => {
      const members = st.members || Object.keys(st.actions || {});
      const action = st.action || st.label || "";
      const memberRows = [
        ...new Set(members.filter((m) => idToRow[m] !== undefined).map((m) => idToRow[m])),
      ].sort((a, b) => a - b);
      let run = [];
      const flush = () => {
        if (!run.length) return;
        const head = run[0];
        textAt[`${head},${ci}`] = action;
        rowspanAt[`${head},${ci}`] = run.length;
        for (const r of run.slice(1)) skip[r][ci] = true;
        run = [];
      };
      for (const r of memberRows) {
        if (run.length && r !== run[run.length - 1] + 1) flush();
        run.push(r);
      }
      flush();
    });
    const cls = dark ? "trn cfe dark" : "trn cfe";
    let html = `<table class="${cls}">`;
    if (banner) {
      html += `<tr class="banner"><td class="ing banner-ing"></td><td class="banner-cell" colspan="${Math.max(
        nCols,
        1
      )}">${esc(banner)}</td></tr>`;
    }
    ingredients.forEach((ing, ri) => {
      const label = ing.raw || ing.name || "";
      html += "<tr>";
      html += `<td class="ing">${esc(label)}</td>`;
      for (let ci = 0; ci < nCols; ci++) {
        if (skip[ri][ci]) continue;
        const span = rowspanAt[`${ri},${ci}`] || 1;
        const txt = textAt[`${ri},${ci}`] || "";
        const rs = span > 1 ? ` rowspan="${span}"` : "";
        const cellCls = txt ? "act" : "empty";
        html += `<td class="${cellCls}"${rs}>${esc(txt)}</td>`;
      }
      html += "</tr>";
    });
    html += "</table>";
    return html;
  }

  function ruleBasedEtrn(recipe) {
    let ingredientsRaw = recipe.ingredients || [];
    let instructions = [...(recipe.instructions || [])];
    if (!ingredientsRaw.length && recipe.raw_text) {
      ingredientsRaw = cleanLines(recipe.raw_text).slice(0, 30);
    }
    if (!instructions.length) {
      instructions = ["Combine and cook according to recipe.", "Serve."];
    }
    let [banner, rest] = extractBanner(instructions);
    instructions = rest;
    if (instructions.length > 12) {
      instructions = instructions.slice(0, 10).concat(instructions.slice(-2));
    }
    const ingObjs = ingredientsRaw.map((raw, i) => {
      const name = ingredientName(raw);
      const prep = raw.includes(",") ? raw.split(",").slice(1).join(",").trim() : "";
      return { id: `i${i}`, qty_us: "", qty_metric: "", name, prep, raw };
    });
    const mainMixture = [];
    const stages = [];
    const firstUse = {};
    instructions.forEach((inst, si) => {
      const action = processAction(inst, si);
      const hits = matchIngredients(inst, ingObjs);
      const low = inst.toLowerCase();
      const isSide =
        /\bin a (?:separate |small )?bowl\b|\bset aside\b|\breserve\b/.test(low) ||
        (hits.length &&
          mainMixture.length &&
          !hits.some((h) => mainMixture.includes(h)) &&
          /\b(mix|combine|whisk)\b/.test(low) &&
          !/\b(add|fold|beat in|stir in)\b/.test(low));
      const streamOnly = /\b(form|shape|scoop|drop|portion|bake|roast|serve|plate|cool|chill|rest)\b/.test(
        low
      );
      let members;
      if (
        hits.length &&
        !(
          streamOnly &&
          !/\b(butter|sugar|flour|egg|salt|oil|milk|cream|cheese|onion|garlic|chicken|beef|pork|fish)\b/.test(
            low
          )
        )
      ) {
        members = [...hits];
        if (!isSide && mainMixture.length) {
          if (
            /\b(add|fold|beat in|stir in|combine)\b/.test(low) ||
            hits.some((h) => mainMixture.includes(h))
          ) {
            const merged = [];
            for (const iid of mainMixture.concat(hits)) {
              if (!merged.includes(iid)) merged.push(iid);
            }
            members = merged;
          }
        }
        if (!isSide) {
          for (const iid of members) {
            if (!mainMixture.includes(iid)) mainMixture.push(iid);
          }
        }
      } else {
        members = mainMixture.length
          ? [...mainMixture]
          : ingObjs[0]
            ? [ingObjs[0].id]
            : [];
      }
      for (const iid of members) {
        if (firstUse[iid] === undefined) firstUse[iid] = si;
      }
      let duration = "";
      const timeM = inst.match(
        /(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))/i
      );
      if (timeM) duration = timeM[1];
      let temp = null;
      const tempM = inst.match(/(\d{2,3})\s*°\s*([FC])/i);
      if (tempM) temp = `${tempM[1]}°${tempM[2].toUpperCase()}`;
      stages.push({
        id: `st${si + 1}`,
        action,
        label: action,
        members,
        duration,
        temp,
        equipment: [],
        actions: Object.fromEntries(members.map((id) => [id, action])),
        produces: "",
      });
    });
    const orderIndex = Object.fromEntries(ingObjs.map((ing, i) => [ing.id, i]));
    ingObjs.sort(
      (a, b) =>
        (firstUse[a.id] ?? 999) - (firstUse[b.id] ?? 999) ||
        orderIndex[a.id] - orderIndex[b.id]
    );
    const idOrder = Object.fromEntries(ingObjs.map((ing, i) => [ing.id, i]));
    for (const st of stages) {
      st.members = [...(st.members || [])].sort(
        (a, b) => (idOrder[a] ?? 999) - (idOrder[b] ?? 999)
      );
    }
    const mise = ingObjs
      .filter((ing) => ing.prep)
      .map((ing) => ({ item: ing.name, notes: `prep: ${ing.prep}` }));
    const md = buildMarkdownTable(ingObjs, stages, banner);
    const html = renderCfeHtml(ingObjs, stages, banner, false);
    return {
      meta: {
        title: recipe.title || "Untitled recipe",
        yield: recipe.yield || "",
        source: recipe.source || "",
        banner,
        total_times: { active: "", passive: "", total: recipe.total_time || "" },
      },
      equipment: [],
      mise_en_place: mise,
      ingredients: ingObjs,
      stages,
      notes: [
        "Cooking for Engineers–style TRN: left = ingredients; right = process timeline; blank cells under an action share that mixture (rowspan).",
      ],
      markdown_table: md,
      html_table: html,
      generator: { path: "rule-based", version: APP_VERSION, format: "cfe-trn" },
    };
  }

  async function llmEtrn(recipe, apiKey, baseUrl, model) {
    const userPayload = {
      title: recipe.title,
      yield: recipe.yield,
      source: recipe.source,
      total_time: recipe.total_time,
      ingredients: recipe.ingredients,
      instructions: recipe.instructions,
      raw_text: (recipe.raw_text || "").slice(0, 8000),
    };
    const res = await fetch(
      `${(baseUrl || DEFAULT_BASE_URL).replace(/\/$/, "")}/chat/completions`,
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${apiKey}`,
        },
        body: JSON.stringify({
          model: model || DEFAULT_MODEL,
          temperature: 0.2,
          messages: [
            { role: "system", content: LLM_SYSTEM_PROMPT },
            {
              role: "user",
              content:
                "Convert this recipe to Cooking-for-Engineers TRN JSON only:\n\n" +
                JSON.stringify(userPayload, null, 2),
            },
          ],
        }),
      }
    );
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`LLM HTTP ${res.status}: ${t.slice(0, 200)}`);
    }
    const body = await res.json();
    let content =
      (body.choices &&
        body.choices[0] &&
        body.choices[0].message &&
        body.choices[0].message.content) ||
      "";
    content = content.trim();
    if (content.startsWith("```")) {
      content = content.replace(/^```(?:json)?\s*/, "").replace(/\s*```$/, "");
    }
    const data = JSON.parse(content);
    const ings = data.ingredients || [];
    const stages = data.stages || [];
    for (const st of stages) {
      if (!st.action && st.label) st.action = st.label;
      if (!st.members) st.members = Object.keys(st.actions || {});
      if (!st.label) st.label = st.action || "";
    }
    const banner = (data.meta && data.meta.banner) || "";
    data.markdown_table = buildMarkdownTable(ings, stages, banner);
    data.html_table = renderCfeHtml(ings, stages, banner, false);
    data.generator = {
      path: "llm",
      model: model || DEFAULT_MODEL,
      base_url: baseUrl || DEFAULT_BASE_URL,
      version: APP_VERSION,
      format: "cfe-trn",
    };
    data.meta = data.meta || {};
    if (!data.meta.title) data.meta.title = recipe.title;
    if (!data.meta.source) data.meta.source = recipe.source;
    return data;
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function printableHtml(etrn) {
    const meta = etrn.meta || {};
    const title = meta.title || "Recipe";
    const banner = meta.banner || "";
    const ings = etrn.ingredients || [];
    const stages = etrn.stages || [];
    const table =
      etrn.html_table || renderCfeHtml(ings, stages, banner, false);
    const yield_ = meta.yield || "";
    const source = meta.source || "";
    const times = meta.total_times || {};
    const sub = [
      yield_ ? `Yield: ${yield_}` : "",
      times.total ? `Total: ${times.total}` : "",
      source ? `Source: ${source}` : "",
    ]
      .filter(Boolean)
      .join(" · ");
    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>${esc(title)} — TRN</title>
<style>
@page{margin:12mm}
body{font-family:system-ui,sans-serif;color:#111;background:#fff;margin:0;padding:16px;font-size:11pt;line-height:1.35}
h1{font-size:18pt;margin:0 0 4px}
.sub{color:#444;font-size:9pt;margin-bottom:14px}
table.trn{border-collapse:collapse;width:100%;font-size:9pt;font-family:ui-monospace,monospace}
table.trn td{border:1px solid #222;padding:5px 7px;vertical-align:middle}
table.trn td.ing{font-weight:600;white-space:nowrap;background:#f4f4f4;text-align:left;max-width:16em}
table.trn td.act{text-align:center;font-weight:600}
table.trn tr.banner td{background:#111;color:#fff;font-weight:600;text-align:left}
table.trn tr.banner td.banner-ing{width:0;padding:0;border-right:0}
.howto{margin-top:18px;font-size:9pt;color:#333}
@media print{body{padding:0}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="sub">${esc(sub)}</div>
${table}
<div class="howto"><strong>How to read this table (Cooking for Engineers TRN).</strong>
Left column = ingredients with quantities. Columns to the right = process timeline (left → right).
An action spanning several rows = one mixture. Blank under an action = still in that mixture.
Separate filled cells in the same column = parallel work.</div>
</body></html>`;
  }

  function safeName(name) {
    return (
      String(name || "recipe")
        .toLowerCase()
        .replace(/[^\w\-]+/g, "-")
        .replace(/^-|-$/g, "")
        .slice(0, 80) || "recipe"
    );
  }

  function showResults(etrn) {
    lastEtrn = etrn;
    results.hidden = false;
    const meta = etrn.meta || {};
    $("result-title").textContent = meta.title || "TRN table";
    const gen = etrn.generator || {};
    $("result-sub").textContent = [
      gen.path ? `path: ${gen.path}` : "",
      "format: cfe-trn",
      meta.yield ? `yield: ${meta.yield}` : "",
      meta.source || "",
      (etrn.ingredients || []).length + " ingredients",
      (etrn.stages || []).length + " process steps",
    ]
      .filter(Boolean)
      .join(" · ");
    const banner = meta.banner || "";
    const table =
      etrn.html_table ||
      renderCfeHtml(etrn.ingredients || [], etrn.stages || [], banner, true);
    $("table-host").innerHTML = table.replace(
      'class="trn cfe"',
      'class="trn cfe dark"'
    );
    $("json-pre").textContent = JSON.stringify(etrn, null, 2);
    $("md-pre").textContent = etrn.markdown_table || "";
    $("print-frame").srcdoc = printableHtml(etrn);
  }

  function downloadJson() {
    if (!lastEtrn) return;
    const blob = new Blob([JSON.stringify(lastEtrn, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = safeName(lastEtrn.meta && lastEtrn.meta.title) + ".etrn.json";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  function downloadHtml() {
    if (!lastEtrn) return;
    const blob = new Blob([printableHtml(lastEtrn)], { type: "text/html" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = safeName(lastEtrn.meta && lastEtrn.meta.title) + ".trn.html";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async function onConvert() {
    const url = ($("url") && $("url").value.trim()) || "";
    const paste = ($("paste") && $("paste").value) || "";
    if (convertBtn) convertBtn.disabled = true;
    setStatus("Working…");
    if (results) results.hidden = true;
    lastEtrn = null;
    try {
      let recipe = null;
      if (url) {
        setStatus("Fetching recipe URL…");
        try {
          recipe = normalizeRecipe(await scrapeUrl(url));
          setStatus("Fetched URL — building CFE matrix…", "ok");
        } catch (e) {
          if (paste.trim()) {
            setStatus(`URL failed (${e.message}); using paste`, "err");
            recipe = normalizeRecipe(parsePasted(paste));
          } else throw e;
        }
      } else if (paste.trim()) {
        setStatus("Parsing paste…");
        recipe = normalizeRecipe(parsePasted(paste));
      } else {
        throw new Error("Provide a recipe URL or paste recipe text.");
      }
      if (
        !recipe ||
        (!(recipe.ingredients && recipe.ingredients.length) &&
          !(recipe.instructions && recipe.instructions.length))
      ) {
        throw new Error(
          "Could not extract ingredients or instructions. Paste a clearer recipe with Ingredients and Instructions headers."
        );
      }
      let etrn;
      if (llmToggle && llmToggle.checked) {
        const key = ($("api-key") && $("api-key").value.trim()) || "";
        if (!key) throw new Error("LLM path requires an API key.");
        try {
          setStatus("Calling LLM…");
          etrn = await llmEtrn(
            recipe,
            key,
            ($("base-url") && $("base-url").value.trim()) || DEFAULT_BASE_URL,
            ($("model") && $("model").value.trim()) || DEFAULT_MODEL
          );
        } catch (e) {
          setStatus(`LLM failed (${e.message}); rule-based fallback`, "err");
          etrn = ruleBasedEtrn(recipe);
        }
      } else {
        etrn = ruleBasedEtrn(recipe);
      }
      showResults(etrn);
      setStatus("Done", "ok");
    } catch (e) {
      console.error("TRN convert failed", e);
      setStatus(e.message || String(e), "err");
    } finally {
      if (convertBtn) convertBtn.disabled = false;
    }
  }
})();
