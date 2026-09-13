import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EvidenceList } from "@/components/evidence/EvidenceList";
import type { EvidenceView } from "@/lib/api/evidence";
import { flushMacrotask } from "@/test-utils";

vi.mock("shiki", () => ({
  codeToHtml: vi.fn(async (code: string) => `<pre><code>${code}</code></pre>`),
}));

const evidence: EvidenceView = {
  chunkId: 1,
  filePath: "app/services/auth.py",
  startLine: 10,
  endLine: 24,
  language: "Python",
  name: "create_access_token",
  score: 0.87,
  text: "def create_access_token(subject):\n    return subject",
  retrievalSources: ["semantic", "keyword"],
};

describe("EvidenceList / EvidenceCitationCard", () => {
  it("shows file path, line range, symbol, and the code snippet", async () => {
    render(<EvidenceList evidence={[evidence]} />);

    expect(screen.getByText("app/services/auth.py:10-24")).toBeInTheDocument();
    expect(screen.getByText("create_access_token")).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText(/semantic \+ keyword/)).toBeInTheDocument();
    await flushMacrotask();
    expect(screen.getByText(/def create_access_token/)).toBeInTheDocument();
  });

  it("renders nothing for an empty evidence list", () => {
    const { container } = render(<EvidenceList evidence={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders multiple citations, each visible without needing to click anything", async () => {
    const second: EvidenceView = {
      ...evidence,
      chunkId: 2,
      filePath: "app/services/other.py",
      startLine: 1,
      endLine: 5,
      name: null,
      retrievalSources: undefined,
    };
    render(<EvidenceList evidence={[evidence, second]} />);

    expect(screen.getByText("Sources (2)")).toBeInTheDocument();
    expect(screen.getByText("app/services/auth.py:10-24")).toBeInTheDocument();
    expect(screen.getByText("app/services/other.py:1-5")).toBeInTheDocument();
  });
});
