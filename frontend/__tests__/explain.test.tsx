import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ExplainPage from "@/app/(app)/repositories/[id]/explain/page";
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

function explainResponse(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: null,
    status: "answered",
    explanation: "This function creates a JWT access token.",
    evidence: [
      {
        chunk_id: 1,
        file_path: "app/core/security.py",
        start_line: 5,
        end_line: 15,
        language: "Python",
        chunk_type: "function",
        name: "create_access_token",
        chunk_text: "def create_access_token(subject):\n    return subject",
        score: 0.9,
        retrieval_sources: ["semantic"],
      },
    ],
    model: "mock-llm",
    ingestion_id: 1,
    input_tokens: 50,
    output_tokens: 10,
    ...overrides,
  };
}

describe("ExplainPage", () => {
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

    renderWithQueryClient(<ExplainPage />);

    expect(await screen.findByText("Repository not found")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows the target-selection form with no result before submission", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));

    renderWithQueryClient(<ExplainPage />);

    await waitFor(() => expect(screen.getByLabelText("File path")).toBeInTheDocument());
    expect(screen.queryByText(/creates a JWT/)).not.toBeInTheDocument();
  });

  it("rejects submission with no file path", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));
    const user = userEvent.setup();
    renderWithQueryClient(<ExplainPage />);

    await waitFor(() => expect(screen.getByLabelText("File path")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Explain" }));

    expect(await screen.findByText("Enter a file path.")).toBeInTheDocument();
  });

  it("submits a file-path-only target and renders the explanation with evidence", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/explain") return jsonResponse(200, explainResponse());
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ExplainPage />);

    await waitFor(() => expect(screen.getByLabelText("File path")).toBeInTheDocument());
    await user.type(screen.getByLabelText("File path"), "app/core/security.py");
    await user.click(screen.getByRole("button", { name: "Explain" }));

    expect(await screen.findByText(/creates a JWT access token/)).toBeInTheDocument();
    expect(screen.getByText("app/core/security.py:5-15")).toBeInTheDocument();
    expect(screen.getByText("create_access_token")).toBeInTheDocument();

    expect(fetch).toHaveBeenCalledWith(
      "/api/bff/repositories/1/explain",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ file_path: "app/core/security.py" }),
      }),
    );
  });

  it("includes start/end line, symbol, and question in the request", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/explain") return jsonResponse(200, explainResponse());
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ExplainPage />);

    await waitFor(() => expect(screen.getByLabelText("File path")).toBeInTheDocument());
    await user.type(screen.getByLabelText("File path"), "app/core/security.py");
    await user.type(screen.getByLabelText(/Symbol/), "create_access_token");
    await user.type(screen.getByLabelText(/Start line/), "5");
    await user.type(screen.getByLabelText(/End line/), "15");
    await user.type(screen.getByLabelText(/Question or focus/), "Is the subject validated?");
    await user.click(screen.getByRole("button", { name: "Explain" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/repositories/1/explain",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            file_path: "app/core/security.py",
            symbol: "create_access_token",
            start_line: 5,
            end_line: 15,
            question: "Is the subject validated?",
          }),
        }),
      ),
    );
  });

  it("rejects an end line before the start line", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));
    const user = userEvent.setup();
    renderWithQueryClient(<ExplainPage />);

    await waitFor(() => expect(screen.getByLabelText("File path")).toBeInTheDocument());
    await user.type(screen.getByLabelText("File path"), "a.py");
    await user.type(screen.getByLabelText(/Start line/), "10");
    await user.type(screen.getByLabelText(/End line/), "5");
    await user.click(screen.getByRole("button", { name: "Explain" }));

    expect(
      await screen.findByText("End line must be greater than or equal to start line."),
    ).toBeInTheDocument();
  });

  it("renders a dedicated insufficient-evidence state, not an error", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/explain")
        return jsonResponse(
          200,
          explainResponse({
            status: "insufficient_evidence",
            explanation: "I could not find enough evidence.",
            evidence: [],
          }),
        );
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ExplainPage />);

    await waitFor(() => expect(screen.getByLabelText("File path")).toBeInTheDocument());
    await user.type(screen.getByLabelText("File path"), "does/not/exist.py");
    await user.click(screen.getByRole("button", { name: "Explain" }));

    expect(await screen.findByText("Not enough evidence to answer")).toBeInTheDocument();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
  });

  it.each([
    [404, "This repository or conversation could not be found."],
    [422, "Bad target"],
    [429, "The AI provider is rate-limited right now. Please try again shortly."],
    [502, "The AI provider is temporarily unavailable. Please try again."],
    [504, "The request timed out. Please try again."],
  ])("shows a friendly error for a %i backend response", async (status, expectedMessage) => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/explain")
        return jsonResponse(status, { detail: "Bad target" });
      return jsonResponse(404, { detail: "not found" });
    });
    const user = userEvent.setup();
    renderWithQueryClient(<ExplainPage />);

    await waitFor(() => expect(screen.getByLabelText("File path")).toBeInTheDocument());
    await user.type(screen.getByLabelText("File path"), "a.py");
    await user.click(screen.getByRole("button", { name: "Explain" }));

    expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
  });
});
