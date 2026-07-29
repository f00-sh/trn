/**
 * POST /api/scrape  { "url": "https://..." }
 * Fetches a recipe page and extracts schema.org/Recipe (JSON-LD) + light heuristics.
 * Used by the static TRN site on Cloudflare Pages (CORS-safe).
 */

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36";

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "POST, OPTIONS",
      "access-control-allow-headers": "content-type",
    },
  });
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

function isoDuration(value) {
  const m = String(value).match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!m) return value;
  const parts = [];
  if (m[1]) parts.push(`${parseInt(m[1], 10)} hr`);
  if (m[2]) parts.push(`${parseInt(m[2], 10)} min`);
  if (m[3] && !parts.length) parts.push(`${parseInt(m[3], 10)} sec`);
  return parts.join(" ") || value;
}

function extractJsonLd(html, source) {
  const re =
    /<script[^>]+type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html))) {
    const raw = m[1].trim();
    if (!raw) continue;
    let data;
    try {
      data = JSON.parse(raw);
    } catch {
      continue;
    }
    const candidates = Array.isArray(data) ? data : [data];
    const expanded = [];
    for (const c of candidates) {
      if (c && c["@graph"]) expanded.push(...c["@graph"]);
      else expanded.push(c);
    }
    for (const node of expanded) {
      if (!node || typeof node !== "object") continue;
      let t = node["@type"] || node.type;
      const types = (Array.isArray(t) ? t : [t]).map((x) =>
        String(x || "").toLowerCase()
      );
      if (!types.some((x) => x.includes("recipe"))) continue;

      const title = String(node.name || "Untitled recipe");
      let yield_ = node.recipeYield || node.yield || "";
      if (Array.isArray(yield_)) yield_ = yield_.join(", ");
      yield_ = String(yield_ || "");

      let rawIngs = node.recipeIngredient || node.ingredients || [];
      let ingredients;
      if (typeof rawIngs === "string") ingredients = cleanLines(rawIngs);
      else ingredients = rawIngs.map((i) => String(i).trim()).filter(Boolean);

      const instructions = [];
      const inst = node.recipeInstructions || node.instructions;
      if (typeof inst === "string") {
        const lines = cleanLines(inst);
        if (lines.length) instructions.push(...lines);
        else {
          instructions.push(
            ...inst
              .split(/(?<=[.!?])\s+/)
              .map((s) => s.trim())
              .filter(Boolean)
          );
        }
      } else if (Array.isArray(inst)) {
        for (const step of inst) {
          if (typeof step === "string") instructions.push(step.trim());
          else if (step && typeof step === "object") {
            if (Array.isArray(step.itemListElement)) {
              for (const sub of step.itemListElement) {
                if (typeof sub === "string") instructions.push(sub.trim());
                else if (sub && (sub.text || sub.name)) {
                  instructions.push(String(sub.text || sub.name).trim());
                }
              }
            } else if (step.text || step.name) {
              instructions.push(String(step.text || step.name).trim());
            }
          }
        }
      }

      let total = node.totalTime || "";
      if (typeof total === "string" && total.startsWith("PT")) {
        total = isoDuration(total);
      }

      return {
        title,
        ingredients: ingredients.filter(Boolean),
        instructions: instructions.filter(Boolean),
        yield: yield_,
        source,
        total_time: String(total || ""),
        raw_text: "",
      };
    }
  }
  return null;
}

function extractHeuristic(html, source) {
  const titleM =
    html.match(/<h1[^>]*>([\s\S]*?)<\/h1>/i) ||
    html.match(/<title[^>]*>([\s\S]*?)<\/title>/i);
  let title = titleM
    ? titleM[1].replace(/<[^>]+>/g, "").trim()
    : "Untitled recipe";
  // Strip scripts/styles roughly
  const text = html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .slice(0, 14000);
  return {
    title,
    ingredients: [],
    instructions: [],
    yield: "",
    source,
    total_time: "",
    raw_text: `${title}\n\n${text}`,
  };
}

export async function onRequestOptions() {
  return json({}, 204);
}

export async function onRequestPost(context) {
  let body;
  try {
    body = await context.request.json();
  } catch {
    return json({ error: "Expected JSON body with url." }, 400);
  }
  const url = String((body && body.url) || "").trim();
  if (!url) return json({ error: "Missing url." }, 400);

  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return json({ error: "Invalid URL." }, 400);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return json({ error: "URL must be http(s)." }, 400);
  }

  let resp;
  try {
    resp = await fetch(url, {
      redirect: "follow",
      headers: {
        "user-agent": UA,
        accept:
          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "accept-language": "en-US,en;q=0.9",
      },
    });
  } catch (e) {
    return json(
      {
        error: `Could not fetch URL: ${e.message || e}. Paste the recipe text instead.`,
      },
      502
    );
  }

  if ([401, 403, 429].includes(resp.status)) {
    return json(
      {
        error: `Site blocked scraping (HTTP ${resp.status}). Paste the recipe text instead.`,
      },
      403
    );
  }
  if (!resp.ok) {
    return json(
      {
        error: `Fetch failed (HTTP ${resp.status}). Paste the recipe text instead.`,
      },
      502
    );
  }

  const html = await resp.text();
  let recipe = extractJsonLd(html, url);
  if (recipe && (recipe.ingredients.length || recipe.instructions.length)) {
    return json({ recipe });
  }

  // Heuristic shell — client paste parser can re-process raw_text if needed
  recipe = extractHeuristic(html, url);
  if (recipe.raw_text && recipe.raw_text.length > 80) {
    return json({
      recipe,
      warning:
        "No schema.org/Recipe found; returned page text. Prefer paste for best results.",
    });
  }

  return json(
    {
      error:
        "No recipe found on that page (blocked, paywall, or non-recipe HTML). Paste the recipe text instead.",
    },
    422
  );
}
