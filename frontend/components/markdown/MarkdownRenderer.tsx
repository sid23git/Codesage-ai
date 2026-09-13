import Markdown, { type Components } from "react-markdown";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";

import { CodeBlock } from "@/components/code/CodeBlock";

/**
 * Renders LLM-generated (or any other untrusted) Markdown text safely.
 *
 * - `rehype-sanitize` (default GitHub-flavored schema) strips raw HTML,
 *   `<script>`, event handlers, and unsafe URL schemes -- this is the
 *   ONLY thing that ever turns Markdown syntax into DOM nodes here; there
 *   is no `dangerouslySetInnerHTML` anywhere in this component.
 * - Fenced code blocks are intercepted and rendered through our own
 *   read-only `CodeBlock` (Shiki) rather than react-markdown's default
 *   `<code>` output, so repository code appearing inside an answer gets
 *   the same safe, syntax-highlighted treatment as evidence snippets.
 * - Links are forced to open in a new tab with `rel="noreferrer noopener"`
 *   and are still subject to the sanitizer's default URL-scheme allowlist
 *   (no `javascript:`/`data:` hrefs survive).
 */
const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noreferrer noopener">
      {children}
    </a>
  ),
  code: ({ className, children }) => {
    const languageMatch = /language-(\w+)/.exec(className ?? "");
    const text = String(children).replace(/\n$/, "");
    // An inline `code` span (no fenced-block language class) stays a
    // plain, inert <code> element; only fenced blocks get the full
    // CodeBlock treatment.
    if (!languageMatch) {
      return <code>{text}</code>;
    }
    return <CodeBlock code={text} language={languageMatch[1]} />;
  },
};

export function MarkdownRenderer({ content }: { content: string }) {
  return (
    <div className="prose prose-sm max-w-none dark:prose-invert prose-p:my-2 prose-pre:p-0 prose-pre:bg-transparent">
      <Markdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeSanitize, defaultSchema]]}
        components={components}
      >
        {content}
      </Markdown>
    </div>
  );
}
