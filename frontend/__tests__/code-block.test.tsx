import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

describe("CodeBlock", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("renders highlighted output from Shiki when it succeeds", async () => {
    vi.doMock("shiki", () => ({
      codeToHtml: vi.fn(async () => '<pre class="shiki"><code><span class="line">highlighted</span></code></pre>'),
    }));
    const { CodeBlock: MockedCodeBlock } = await import("@/components/code/CodeBlock");

    render(<MockedCodeBlock code="def f(): pass" language="python" />);

    expect(await screen.findByText("highlighted")).toBeInTheDocument();
  });

  it("falls back to a plain, inert <pre> when highlighting fails, never interpreting the source as HTML", async () => {
    vi.doMock("shiki", () => ({
      codeToHtml: vi.fn(async () => {
        throw new Error("unknown language");
      }),
    }));
    const { CodeBlock: MockedCodeBlock } = await import("@/components/code/CodeBlock");

    const maliciousSource = '<script>window.__codeBlockPwned = true</script>';
    const { container } = render(
      <MockedCodeBlock code={maliciousSource} language="does-not-exist" />,
    );

    await waitFor(() => expect(container.querySelector("pre")).toBeInTheDocument());
    // The literal text is present (as inert text, not interpreted markup)...
    expect(container.querySelector("code")).toHaveTextContent(maliciousSource);
    // ...and no actual <script> element was ever created from it.
    expect(container.querySelector("script")).not.toBeInTheDocument();
    expect(
      (window as unknown as { __codeBlockPwned?: boolean }).__codeBlockPwned,
    ).toBeUndefined();
  });
});
