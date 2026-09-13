import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "@/app/(app)/repositories/[id]/review/page";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

vi.mock("shiki", () => ({
  codeToHtml: vi.fn(async (code: string) => `<pre><code>${code}</code></pre>`),
}));

let currentSearchParams = new URLSearchParams();
let currentId = "1";
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: currentId }),
  useSearchParams: () => currentSearchParams,
}));

const repo = {
  id: 1,
  owner_id: 1,
  name: "my-repo",
  full_name: "octocat/my-repo",
  github_url: "https://github.com/octocat/my-repo",
  description: null,
  primary_language: "Python",
  status: "ready",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  github_repository_id: null,
  github_owner: null,
  default_branch: null,
  stars: null,
  forks: null,
  open_issues: null,
  github_updated_at: null,
  last_synced_at: null,
};

function routeFor(url: string) {
  return url.replace(/^\/api\/bff\//, "");
}

function reviewResponse(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: null,
    status: "answered",
    summary: "Overall the code looks reasonable with one issue.",
    findings: [
      {
        title: "Missing input validation",
        severity: "medium",
        category: "bug",
        explanation: "The amount is not validated before use.",
        recommendation: "Validate that amount is positive.",
        file_path: "svc.py",
        start_line: 1,
        end_line: 2,
        evidence_chunk_ids: [1],
      },
    ],
    evidence: [
      {
        chunk_id: 1,
        file_path: "svc.py",
        start_line: 1,
        end_line: 5,
        language: "Python",
        chunk_type: "function",
        name: "process_payment",
        chunk_text: "def process_payment(amount):\n    charge(amount)",
        score: 0.88,
        retrieval_sources: ["semantic"],
      },
    ],
    model: "mock-llm",
    ingestion_id: 1,
    input_tokens: 80,
    output_tokens: 20,
    ...overrides,
  };
}

describe("ReviewPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    currentSearchParams = new URLSearchParams();
    currentId = "1";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a not-found state (not a blank page) for a malformed repository id in the URL", async () => {
    currentId = "not-a-number";
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));

    renderWithQueryClient(<ReviewPage />);

    expect(await screen.findByText("Repository not found")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows a validation message for a symbol name that's too long", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));

    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);
    await waitFor(() => expect(screen.getByLabelText("Symbol (optional)")).toBeEnabled());

    await user.type(screen.getByLabelText("File path (repository target)"), "app/x.py");
    await user.type(screen.getByLabelText("Symbol (optional)"), "a".repeat(256));
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(
      await screen.findByText("Symbol must be at most 255 characters."),
    ).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith(
      "/api/bff/repositories/1/review",
      expect.anything(),
    );
  });

  it("shows the target-selection form with no result before submission", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));

    renderWithQueryClient(<ReviewPage />);

    await waitFor(() =>
      expect(screen.getByLabelText("File path (repository target)")).toBeInTheDocument(),
    );
    expect(screen.queryByText("Summary")).not.toBeInTheDocument();
  });

  it("requires a file path or user-provided code before submitting", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));
    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);

    await waitFor(() =>
      expect(screen.getByLabelText("File path (repository target)")).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(
      await screen.findByText("Provide a file path or paste code to review."),
    ).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith(
      "/api/bff/repositories/1/review",
      expect.anything(),
    );
  });

  it("reviews a repository file target and renders structured findings + summary", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/review") return jsonResponse(200, reviewResponse());
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);

    await waitFor(() =>
      expect(screen.getByLabelText("File path (repository target)")).toBeInTheDocument(),
    );
    await user.type(screen.getByLabelText("File path (repository target)"), "svc.py");
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(await screen.findByText("Overall the code looks reasonable with one issue.")).toBeInTheDocument();
    expect(screen.getByText("Missing input validation")).toBeInTheDocument();
    expect(screen.getByText("medium")).toBeInTheDocument();
    expect(screen.getByText("bug")).toBeInTheDocument();
    expect(screen.getByText("Validate that amount is positive.")).toBeInTheDocument();
    expect(screen.getByText("svc.py:1-2")).toBeInTheDocument();
    // Findings reference their supporting evidence by file:line.
    expect(screen.getByText(/Supported by:.*svc\.py:1-5/)).toBeInTheDocument();
    // The shared EvidenceList is reused underneath, unmodified.
    expect(screen.getByText("Sources (1)")).toBeInTheDocument();
  });

  it("sends the selected review focus", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/review") return jsonResponse(200, reviewResponse());
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);

    await waitFor(() =>
      expect(screen.getByLabelText("File path (repository target)")).toBeInTheDocument(),
    );
    await user.type(screen.getByLabelText("File path (repository target)"), "svc.py");
    await user.selectOptions(screen.getByLabelText("Focus"), "security");
    await user.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/repositories/1/review",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ file_path: "svc.py", focus: "security" }),
        }),
      ),
    );
  });

  it("submits user-provided code and labels it as untrusted, distinct from repository evidence", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/review")
        return jsonResponse(
          200,
          reviewResponse({ evidence: [], findings: [] }),
        );
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);

    await waitFor(() => expect(screen.getByLabelText(/paste code\/diff/i)).toBeInTheDocument());
    await user.type(screen.getByLabelText(/paste code\/diff/i), "def f(): pass");
    await user.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/repositories/1/review",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ focus: "general", user_code: "def f(): pass" }),
        }),
      ),
    );
    expect(
      await screen.findByText(/covers the user-provided code above \(untrusted input\)/),
    ).toBeInTheDocument();
  });

  it("accepts exactly 20,000 characters of user code", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/review")
        return jsonResponse(200, reviewResponse({ evidence: [], findings: [] }));
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);

    const textarea = await screen.findByLabelText(/paste code\/diff/i);
    const exactly20000 = "a".repeat(20000);
    fireEvent.change(textarea, { target: { value: exactly20000 } });

    expect(screen.getByText("20,000 / 20,000")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/repositories/1/review",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("rejects user code over 20,000 characters before submitting", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));
    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);

    const textarea = await screen.findByLabelText(/paste code\/diff/i);
    const tooLong = "a".repeat(20001);
    fireEvent.change(textarea, { target: { value: tooLong } });

    expect(screen.getByText("20,001 / 20,000")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(
      await screen.findByText("Code must be at most 20,000 characters."),
    ).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith(
      "/api/bff/repositories/1/review",
      expect.anything(),
    );
  });

  it("renders a dedicated insufficient-evidence state, not an error", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/review")
        return jsonResponse(
          200,
          reviewResponse({
            status: "insufficient_evidence",
            summary: "Not enough evidence.",
            findings: [],
            evidence: [],
          }),
        );
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);

    await waitFor(() =>
      expect(screen.getByLabelText("File path (repository target)")).toBeInTheDocument(),
    );
    await user.type(screen.getByLabelText("File path (repository target)"), "unknown.py");
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(await screen.findByText("Not enough evidence to answer")).toBeInTheDocument();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it.each([
    [404, "This repository or conversation could not be found."],
    [422, "No reviewable target"],
    [429, "The AI provider is rate-limited right now. Please try again shortly."],
    [502, "The AI provider is temporarily unavailable. Please try again."],
    [504, "The request timed out. Please try again."],
  ])("shows a friendly error for a %i backend response", async (status, expectedMessage) => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/review")
        return jsonResponse(status, { detail: "No reviewable target" });
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ReviewPage />);

    await waitFor(() =>
      expect(screen.getByLabelText("File path (repository target)")).toBeInTheDocument(),
    );
    await user.type(screen.getByLabelText("File path (repository target)"), "a.py");
    await user.click(screen.getByRole("button", { name: "Review" }));

    expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
  });
});
