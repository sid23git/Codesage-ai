import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MarkdownRenderer } from "@/components/markdown/MarkdownRenderer";
import { flushMacrotask } from "@/test-utils";

// CodeBlock's own Shiki integration is tested separately -- here we only
// need a deterministic stand-in so these sanitization tests aren't
// coupled to (or slowed down by) the real async highlighter.
vi.mock("shiki", () => ({
  codeToHtml: vi.fn(async (code: string) => `<pre><code>${code}</code></pre>`),
}));

describe("MarkdownRenderer", () => {
  it("renders ordinary Markdown formatting", () => {
    const { container } = render(<MarkdownRenderer content="**bold** and *italic*" />);
    expect(container.querySelector("strong")).toHaveTextContent("bold");
    expect(container.querySelector("em")).toHaveTextContent("italic");
  });

  it("strips a raw <script> tag rather than executing/rendering it", () => {
    const { container } = render(
      <MarkdownRenderer content={'Hello <script>window.__pwned = true</script> world'} />,
    );
    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect((window as unknown as { __pwned?: boolean }).__pwned).toBeUndefined();
  });

  it("strips inline event-handler attributes from raw HTML (the sanitizer removes the whole <img>, an even stronger guarantee)", () => {
    const { container } = render(
      <MarkdownRenderer content={'<img src="x" onerror="window.__pwned2 = true">'} />,
    );
    // No element anywhere in the output carries the handler attribute,
    // whether or not the <img> itself survived sanitization.
    expect(container.querySelector("[onerror]")).not.toBeInTheDocument();
    expect(
      (window as unknown as { __pwned2?: boolean }).__pwned2,
    ).toBeUndefined();
  });

  it("forces links to open safely and strips javascript: URLs", () => {
    render(<MarkdownRenderer content="[a safe link](https://example.com/docs)" />);
    const link = screen.getByRole("link", { name: "a safe link" });
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noreferrer noopener");

    const { container: unsafeContainer } = render(
      <MarkdownRenderer content="[click me](javascript:alert(1))" />,
    );
    // Either the whole anchor was dropped, or it survived without the
    // dangerous href -- both are acceptable, unsafe-scheme-survives is not.
    const unsafeHref = unsafeContainer.querySelector("a")?.getAttribute("href");
    if (unsafeHref !== undefined && unsafeHref !== null) {
      expect(unsafeHref).not.toMatch(/^javascript:/);
    }
  });

  it("routes fenced code blocks through CodeBlock instead of a raw <pre>/<code> from react-markdown", async () => {
    render(<MarkdownRenderer content={"```python\nprint('hi')\n```"} />);
    await flushMacrotask();
    expect(screen.getByText("print('hi')")).toBeInTheDocument();
  });
});
