"use client";

import { useEffect, useState } from "react";
import type { ShikiTransformer } from "shiki";
import { codeToHtml } from "shiki";

/**
 * Read-only, syntax-highlighted code display for repository source and
 * evidence snippets. Repository/LLM content is never trusted:
 *
 * - `code` is passed to Shiki as a plain string; Shiki tokenizes it and
 *   produces HTML with the source text HTML-escaped into the output --
 *   it is never parsed or executed as markup, and this component never
 *   evaluates it in any way.
 * - The one `dangerouslySetInnerHTML` below renders ONLY Shiki's own
 *   generated HTML (which re-escapes the input), never the raw `code`
 *   string directly -- this is the standard, necessary integration
 *   pattern for a highlighter whose public API returns an HTML string.
 * - Until highlighting finishes (or if it fails for an unrecognized
 *   language), a plain `<pre>` fallback is rendered instead, using the
 *   code as ordinary React text content (auto-escaped by React, no HTML
 *   interpretation either way).
 */

const THEME = "github-dark";

function lineNumberTransformer(startLine: number): ShikiTransformer {
  return {
    name: "codesage-line-numbers",
    line(node, line) {
      this.addClassToHast(node, "line");
      node.children.unshift({
        type: "element",
        tagName: "span",
        properties: { className: ["line-number"] },
        children: [{ type: "text", value: String(startLine + line - 1) }],
      });
    },
  };
}

export function CodeBlock({
  code,
  language,
  startLine = 1,
}: {
  code: string;
  language?: string | null;
  startLine?: number;
}) {
  const [html, setHtml] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    codeToHtml(code, {
      lang: language || "text",
      theme: THEME,
      transformers: [lineNumberTransformer(startLine)],
    })
      .then((result) => {
        if (!cancelled) setHtml(result);
      })
      .catch(() => {
        // Unrecognized language identifier, etc. -- fall back to the
        // plain <pre> below rather than failing the whole page.
        if (!cancelled) setHtml(null);
      });

    return () => {
      cancelled = true;
    };
  }, [code, language, startLine]);

  if (html) {
    return (
      <div
        className="shiki-container overflow-x-auto rounded-md text-sm"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  return (
    <pre className="overflow-x-auto rounded-md bg-muted p-3 text-sm">
      <code>{code}</code>
    </pre>
  );
}
