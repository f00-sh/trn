/* TRN site converter — rule-based + optional LLM (browser). */
(() => {
  "use strict";

  const APP_VERSION = "0.1.0";
  const DEFAULT_BASE_URL = "https://api.x.ai/v1";
  const DEFAULT_MODEL = "grok-3";

  const LLM_SYSTEM_PROMPT = `You are an expert at converting traditional recipes into Enhanced Tabular Recipe Notation (eTRN) inspired by Cooking for Engineers' Tabular Recipe Notation.
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
Make markdown_table dense and scannable like classic Cooking for Engineers tables.`;

  const ACTION_KEYWORDS = [
    ["prep", ["chop", "dice", "mince", "slice", "peel", "grate", "zest", "measure", "sift"]],
    ["melt", ["melt", "soften"]],
    ["heat", ["heat", "warm", "preheat", "bring to"]],
    ["saute", ["saute", "sauté", "fry", "brown the", "until brown", "sear", "sweat"]],
    ["mix", ["mix", "stir", "whisk", "beat", "cream", "fold", "combine", "blend"]],
    ["simmer", ["simmer", "boil", "poach", "reduce", "braise", "stew"]],
    ["bake", ["bake", "roast", "broil", "grill", "toast", "oven"]],
    ["rest", ["rest", "cool", "chill", "refrigerate", "freeze", "marinate", "proof", "rise", "sit"]],
    ["finish", ["serve", "plate", "garnish", "drizzle", "top", "season", "adjust", "transfer", "pour"]],
  ];

  const STOPWORDS = new Set([
    "a", "an", "the", "and", "or", "of", "to", "in", "into", "with", "for", "on",
    "until", "about", "over", "under", "by", "from", "as", "at", "is", "are",
    "be", "cup", "cups", "tbsp", "tsp", "tablespoon", "teaspoon", "tablespoons",
    "teaspoons", "ounce", "ounces", "oz", "lb", "lbs", "pound", "pounds", "g",
    "kg", "ml", "l", "optional", "plus", "more",
  ]);

  // --- DOM ---
  const $ = (id) => document.getElementById(id);
  const llmToggle = $("llm-toggle");
  const llmSettings = $("llm-settings");
  const convertBtn = $("convert-btn");
  const statusEl = $("status");
  const results = $("results");

  llmToggle.addEventListener("change", () => {
    llmSettings.hidden = !llmToggle.checked;
  });

  convertBtn.addEventListener("click", onConvert);
  $("dl-json").addEventListener("click", () => downloadJson());
  $("dl-html").addEventListener("click", () => downloadHtml());
  $("print-btn").addEventListener("click", () => {
    const frame = $("print-frame");
    if (frame && frame.contentWindow) frame.contentWindow.print();
  });

  let lastEtrn = null;

  function setStatus(msg, kind) {
    statusEl.textContent = msg || "";
    statusEl.classList.remove("err", "ok");
    if (kind) statusEl.classList.add(kind);
  }

  // --- Parse paste ---
  function cleanLines(text) {
    return text
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
    const ingM = text.match(/(?im)^(ingredients?)\s*:?\s*$/m);
    const instM = text.match(
      /(?im)^(instructions?|directions?|method|steps?|preparation)\s*:?\s*$/m
    );
    let title = "Untitled recipe";
    let ingredients = [];
    let instructions = [];

    if (ingM && instM && ingM.index < instM.index) {
      const head = text.slice(0, ingM.index).trim();
      if (head) title = head.split(/\r?\n/)[0].trim() || title;
      const ingBlock = text.slice(ingM.index + ingM[0].length, instM.index);
      const instBlock = text.slice(instM.index + instM[0].length);
      ingredients = cleanLines(ingBlock);
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
    return { title, ingredients, instructions, yield: "", source: "", total_time: "", raw_text: text };
  }

  // --- Scrape via Pages Function ---
  async function scrapeUrl(url) {
    const res = await fetch("/api/scrape", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ url }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.error || `Scrape failed (HTTP ${res.status})`);
    }
    return data.recipe;
  }

  // --- Rule-based eTRN ---
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
    return new Set(toks.filter((t) => !STOPWORDS.has(t) && t.length > 2));
  }

  function hasKw(text, kw) {
    const re = new RegExp(`(?<![a-z])${kw.replace(/[.*+?^${}()|[\\]\\\\]/g, "\\$&")}(?![a-z])`, "i");
    return re.test(text);
  }

  function stageLabel(instruction, index) {
    const low = instruction.toLowerCase();
    const temp = instruction.match(/(\d{2,3})\s*°\s*([FC])/i);
    const timeM = instruction.match(
      /(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?|seconds?|secs?))/i
    );
    for (const [label, kws] of ACTION_KEYWORDS) {
      for (const kw of kws) {
        if (hasKw(low, kw)) {
          let parts = [label];
          if (temp && ["bake", "heat", "roast", "broil", "grill"].includes(label)) {
            parts = [`${label} ${temp[1]}°${temp[2].toUpperCase()}`];
          }
          if (timeM && ["bake", "simmer", "rest", "cook", "roast"].includes(label)) {
            let t = timeM[1].toLowerCase().replace(/\s+/g, "");
            t = t.replace(/minutes?/, "min").replace(/hours?/, "hr");
            parts.push(t);
          }
          return parts.join(" ").slice(0, 40);
        }
      }
    }
    const words = instruction.match(/[A-Za-z0-9°]+/g) || [];
    if (!words.length) return `step ${index + 1}`;
    return words.slice(0, 4).join(" ").toLowerCase().slice(0, 32);
  }

  function cellAction(instruction, ingName) {
    const low = instruction.toLowerCase();
    for (const [, kws] of ACTION_KEYWORDS) {
      for (const kw of kws) {
        if (hasKw(low, kw)) {
          const until = instruction.match(/until\s+([^.;,]{3,40})/i);
          const temp = instruction.match(/(\d{2,3}\s*°\s*[FC])/i);
          const bits = [kw];
          if (temp && ["bake", "heat", "roast", "preheat", "cook"].includes(kw)) {
            bits.push(temp[1].replace(/\s+/g, ""));
          }
          if (until && ["cook", "bake", "simmer", "brown", "stir", "whisk"].includes(kw)) {
            bits.push("until " + until[1].trim().slice(0, 24));
          }
          if (instruction.length < 60) return instruction.trim().slice(0, 48);
          return bits.join(" ").slice(0, 48);
        }
      }
    }
    const first = (ingName.toLowerCase().split(/\s+/)[0] || "");
    const idx = first ? low.indexOf(first) : -1;
    if (idx >= 0) {
      const snippet = instruction.slice(Math.max(0, idx - 20), idx + 40).trim();
      return snippet.replace(/^\W+|\W+$/g, "").slice(0, 48) || "use";
    }
    return "add";
  }

  function buildMarkdownTable(ingredients, stages) {
    const headers = ["Ingredient", ...stages.map((s) => s.label)];
    const sep = headers.map(() => "---");
    const lines = [
      "| " + headers.join(" | ") + " |",
      "| " + sep.join(" | ") + " |",
    ];
    for (const ing of ingredients) {
      let label = ing.raw || ing.name || "";
      if (label.length > 48) label = ing.name || label.slice(0, 48);
      const cells = [label];
      for (const st of stages) {
        cells.push((st.actions && st.actions[ing.id]) || "");
      }
      lines.push("| " + cells.map((c) => String(c).replace(/\|/g, "/")).join(" | ") + " |");
    }
    return lines.join("\n");
  }

  function ruleBasedEtrn(recipe) {
    let ingredientsRaw = recipe.ingredients || [];
    let instructions = recipe.instructions || [];
    if (!ingredientsRaw.length && recipe.raw_text) {
      ingredientsRaw = cleanLines(recipe.raw_text).slice(0, 30);
    }
    if (!instructions.length) {
      instructions = ["Combine and cook according to recipe.", "Serve."];
    }
    let stagesSrc = instructions.slice(0, 12);
    if (instructions.length > 12) {
      stagesSrc = instructions.slice(0, 10).concat(instructions.slice(-2));
    }

    const ingObjs = ingredientsRaw.map((raw, i) => {
      const name = ingredientName(raw);
      const prep = raw.includes(",") ? raw.split(",").slice(1).join(",").trim() : "";
      return { id: `i${i}`, qty_us: "", qty_metric: "", name, prep, raw };
    });

    const stages = stagesSrc.map((inst, si) => {
      const label = stageLabel(inst, si);
      const actions = {};
      const instTokens = nameTokens(inst);
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
          const low = inst.toLowerCase();
          for (const t of tokens) {
            if (t.length > 3 && low.includes(t)) {
              hit = true;
              break;
            }
          }
        }
        if (hit) actions[ing.id] = cellAction(inst, ing.name);
      }
      let duration = "";
      const timeM = inst.match(/(\d+\s*(?:-\s*\d+)?\s*(?:minutes?|mins?|hours?|hrs?))/i);
      if (timeM) duration = timeM[1];
      let temp = null;
      const tempM = inst.match(/(\d{2,3})\s*°\s*([FC])/i);
      if (tempM) temp = `${tempM[1]}°${tempM[2].toUpperCase()}`;
      return {
        id: `st${si + 1}`,
        label,
        duration,
        temp,
        equipment: [],
        actions,
        produces: "",
      };
    });

    const firstUse = {};
    stages.forEach((st, si) => {
      Object.keys(st.actions).forEach((iid) => {
        if (firstUse[iid] === undefined) firstUse[iid] = si;
      });
    });
    ingObjs.sort((a, b) => (firstUse[a.id] ?? 999) - (firstUse[b.id] ?? 999) || a.id.localeCompare(b.id));

    const mise = [];
    for (const ing of ingObjs) {
      if (ing.prep && firstUse[ing.id] === undefined) {
        mise.push({ item: ing.name, notes: ing.prep });
      } else if (ing.prep) {
        mise.push({ item: ing.name, notes: `prep: ${ing.prep}` });
      }
    }

    const md = buildMarkdownTable(ingObjs, stages);
    return {
      meta: {
        title: recipe.title || "Untitled recipe",
        yield: recipe.yield || "",
        source: recipe.source || "",
        total_times: { active: "", passive: "", total: recipe.total_time || "" },
      },
      equipment: [],
      mise_en_place: mise,
      ingredients: ingObjs,
      stages,
      notes: [
        "Generated by TRN rule-based converter. Toggle LLM path for denser stage labels.",
      ],
      markdown_table: md,
      generator: { path: "rule-based", version: APP_VERSION },
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
    const res = await fetch(`${(baseUrl || DEFAULT_BASE_URL).replace(/\/$/, "")}/chat/completions`, {
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
              "Convert this recipe to eTRN JSON only:\n\n" +
              JSON.stringify(userPayload, null, 2),
          },
        ],
      }),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`LLM HTTP ${res.status}: ${t.slice(0, 200)}`);
    }
    const body = await res.json();
    let content = (body.choices && body.choices[0] && body.choices[0].message && body.choices[0].message.content) || "";
    content = content.trim();
    if (content.startsWith("```")) {
      content = content.replace(/^```(?:json)?\s*/, "").replace(/\s*```$/, "");
    }
    const data = JSON.parse(content);
    if (!data.markdown_table) {
      data.markdown_table = buildMarkdownTable(data.ingredients || [], data.stages || []);
    }
    data.generator = {
      path: "llm",
      model: model || DEFAULT_MODEL,
      base_url: baseUrl || DEFAULT_BASE_URL,
      version: APP_VERSION,
    };
    data.meta = data.meta || {};
    if (!data.meta.title) data.meta.title = recipe.title;
    if (!data.meta.source) data.meta.source = recipe.source;
    return data;
  }

  // --- Render ---
  function esc(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function mdTableToHtml(md) {
    const lines = md
      .trim()
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean);
    if (lines.length < 2) return `<pre>${esc(md)}</pre>`;
    const rows = [];
    for (const ln of lines) {
      if (/^\|?\s*:?---/.test(ln)) continue;
      rows.push(ln.replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim()));
    }
    if (!rows.length) return `<pre>${esc(md)}</pre>`;
    const head = rows[0];
    const body = rows.slice(1);
    const th = head.map((c) => `<th>${esc(c)}</th>`).join("");
    const trs = body
      .map((r) => {
        while (r.length < head.length) r.push("");
        return (
          "<tr>" +
          r
            .slice(0, head.length)
            .map((c) => `<td>${esc(c)}</td>`)
            .join("") +
          "</tr>"
        );
      })
      .join("");
    return `<table class="trn"><thead><tr>${th}</tr></thead><tbody>${trs}</tbody></table>`;
  }

  function printableHtml(etrn) {
    const meta = etrn.meta || {};
    const title = meta.title || "Recipe";
    const yield_ = meta.yield || "";
    const source = meta.source || "";
    const times = meta.total_times || {};
    const table = mdTableToHtml(etrn.markdown_table || "");
    const mise = etrn.mise_en_place || [];
    const notes = etrn.notes || [];
    let miseHtml = "";
    if (mise.length) {
      miseHtml =
        "<h2>Mise en place</h2><ul>" +
        mise
          .filter((m) => m.item)
          .map(
            (m) =>
              `<li><strong>${esc(m.item)}</strong>${m.notes ? " — " + esc(m.notes) : ""}</li>`
          )
          .join("") +
        "</ul>";
    }
    let notesHtml = "";
    if (notes.length) {
      notesHtml =
        "<h2>Notes</h2><ul>" + notes.map((n) => `<li>${esc(String(n))}</li>`).join("") + "</ul>";
    }
    const sub = [
      yield_ ? `Yield: ${yield_}` : "",
      times.total ? `Total: ${times.total}` : "",
      source ? `Source: ${source}` : "",
    ]
      .filter(Boolean)
      .join(" · ");

    return `<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>${esc(title)} — eTRN</title>
<style>
@page{margin:12mm}
body{font-family:system-ui,sans-serif;color:#111;background:#fff;margin:0;padding:16px;font-size:11pt;line-height:1.35}
h1{font-size:18pt;margin:0 0 4px}
.sub{color:#444;font-size:9pt;margin-bottom:14px}
table.trn{border-collapse:collapse;width:100%;font-size:9pt;font-family:ui-monospace,monospace}
table.trn th,table.trn td{border:1px solid #222;padding:4px 6px;vertical-align:top}
table.trn th{background:#111;color:#fff;font-weight:600;text-align:left}
table.trn td:first-child,table.trn th:first-child{font-weight:600;white-space:nowrap;max-width:14em}
table.trn tr:nth-child(even) td{background:#f6f6f6}
h2{font-size:12pt;margin:16px 0 6px}
ul{margin:0 0 8px 1.2em;padding:0}
.howto{margin-top:18px;font-size:9pt;color:#333}
@media print{body{padding:0}}
</style></head><body>
<h1>${esc(title)}</h1>
<div class="sub">${esc(sub)}</div>
${table}
${miseHtml}
${notesHtml}
<div class="howto"><strong>How to read this table.</strong>
Rows are ingredients in first-use order. Columns are chronological process stages.
A cell holds the short action for that ingredient in that stage; empty means idle.
Read left → right across a row to follow one ingredient; read a column for one stage.</div>
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
    $("result-title").textContent = meta.title || "eTRN table";
    const gen = etrn.generator || {};
    $("result-sub").textContent = [
      gen.path ? `path: ${gen.path}` : "",
      meta.yield ? `yield: ${meta.yield}` : "",
      meta.source ? meta.source : "",
      (etrn.ingredients || []).length + " ingredients",
      (etrn.stages || []).length + " stages",
    ]
      .filter(Boolean)
      .join(" · ");

    $("table-host").innerHTML = mdTableToHtml(etrn.markdown_table || "");
    $("json-pre").textContent = JSON.stringify(etrn, null, 2);
    $("md-pre").textContent = etrn.markdown_table || "";
    const html = printableHtml(etrn);
    const frame = $("print-frame");
    frame.srcdoc = html;
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
    const url = $("url").value.trim();
    const paste = $("paste").value;
    convertBtn.disabled = true;
    setStatus("Working…");
    results.hidden = true;
    lastEtrn = null;

    try {
      let recipe = null;
      if (url) {
        try {
          recipe = await scrapeUrl(url);
          setStatus("Fetched URL", "ok");
        } catch (e) {
          if (paste.trim()) {
            setStatus(`URL failed (${e.message}); using paste`, "err");
            recipe = parsePasted(paste);
          } else {
            throw e;
          }
        }
      } else if (paste.trim()) {
        recipe = parsePasted(paste);
      } else {
        throw new Error("Provide a recipe URL or paste recipe text.");
      }

      if (!recipe || (!(recipe.ingredients && recipe.ingredients.length) && !(recipe.instructions && recipe.instructions.length))) {
        throw new Error(
          "Could not extract ingredients or instructions. Paste a clearer recipe with Ingredients and Instructions headers."
        );
      }

      let etrn;
      if (llmToggle.checked) {
        const key = $("api-key").value.trim();
        if (!key) throw new Error("LLM path requires an API key.");
        try {
          etrn = await llmEtrn(
            recipe,
            key,
            $("base-url").value.trim() || DEFAULT_BASE_URL,
            $("model").value.trim() || DEFAULT_MODEL
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
      setStatus(e.message || String(e), "err");
    } finally {
      convertBtn.disabled = false;
    }
  }
})();
