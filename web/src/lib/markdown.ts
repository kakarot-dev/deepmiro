/** Markdown renderer for report content.
 *
 * Supports fenced ```mermaid blocks — they are emitted as a sanitized
 * placeholder div with a data-attribute holding the raw source, and a
 * separate `renderMermaidIn(root)` helper lazy-loads mermaid and swaps
 * the placeholders for SVG. We do the two-step dance so the markdown
 * output stays trivially sanitizable (no SVG passes through DOMPurify).
 */

import MarkdownIt from "markdown-it";
import DOMPurify from "dompurify";

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  typographer: true,
});

const defaultFence = md.renderer.rules.fence!;
md.renderer.rules.fence = function (tokens, idx, options, env, self) {
  const token = tokens[idx];
  const info = (token.info || "").trim().toLowerCase();
  if (info === "mermaid") {
    const src = token.content || "";
    const encoded = encodeURIComponent(src);
    return `<div class="mermaid-chart" data-mermaid="${encoded}"><pre class="mermaid-fallback">${md.utils.escapeHtml(src)}</pre></div>`;
  }
  return defaultFence(tokens, idx, options, env, self);
};

export function renderMarkdown(source: string): string {
  if (!source) return "";
  const rendered = md.render(source);
  return DOMPurify.sanitize(rendered, {
    ALLOWED_TAGS: [
      "h1", "h2", "h3", "h4", "h5", "h6",
      "p", "br", "hr",
      "strong", "em", "b", "i", "u", "s", "del", "mark",
      "ul", "ol", "li",
      "blockquote",
      "code", "pre",
      "a",
      "table", "thead", "tbody", "tr", "th", "td",
      "img",
      "div", "span",
    ],
    ALLOWED_ATTR: ["href", "title", "src", "alt", "target", "rel", "class", "data-mermaid"],
  });
}

interface MermaidApi {
  initialize: (cfg: Record<string, unknown>) => void;
  render: (id: string, src: string) => Promise<{ svg: string }>;
}

let mermaidPromise: Promise<MermaidApi> | null = null;
let mermaidInitialized = false;

async function loadMermaid(): Promise<MermaidApi> {
  if (!mermaidPromise) {
    mermaidPromise = import(/* @vite-ignore */ "mermaid").then(
      (m: { default: MermaidApi }) => m.default,
    );
  }
  const mermaid = await mermaidPromise;
  if (!mermaidInitialized) {
    mermaid.initialize({
      startOnLoad: false,
      theme: "dark",
      securityLevel: "strict",
      themeVariables: {
        primaryColor: "#22d3ee",
        primaryTextColor: "#e2e8f0",
        lineColor: "#94a3b8",
        background: "transparent",
      },
    });
    mermaidInitialized = true;
  }
  return mermaid;
}

/** Find every `.mermaid-chart` placeholder under `root` and replace its
 *  contents with rendered SVG. Safe to call multiple times. */
export async function renderMermaidIn(root: HTMLElement | null): Promise<void> {
  if (!root) return;
  const placeholders = Array.from(
    root.querySelectorAll<HTMLElement>(".mermaid-chart[data-mermaid]"),
  );
  if (placeholders.length === 0) return;
  let mermaid;
  try {
    mermaid = await loadMermaid();
  } catch (err) {
    console.warn("Mermaid load failed:", err);
    return;
  }
  for (let i = 0; i < placeholders.length; i += 1) {
    const el = placeholders[i];
    const raw = el.dataset.mermaid ?? "";
    if (!raw) continue;
    const src = decodeURIComponent(raw);
    const id = `mermaid-${Date.now()}-${i}-${Math.floor(Math.random() * 1e6)}`;
    try {
      const { svg } = await mermaid.render(id, src);
      el.innerHTML = svg;
      el.removeAttribute("data-mermaid");
    } catch (err) {
      // Keep the <pre> fallback that's already in the placeholder so the
      // user sees the raw chart source instead of a blank box.
      console.warn("Mermaid render failed:", err);
    }
  }
}
