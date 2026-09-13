import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AskPage from "@/app/(app)/repositories/[id]/ask/page";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

vi.mock("shiki", () => ({
  codeToHtml: vi.fn(async (code: string) => `<pre><code>${code}</code></pre>`),
}));

const routerReplace = vi.fn();
let currentSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "1" }),
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
  usePathname: () => "/repositories/1/ask",
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

function answeredResponse(overrides: Record<string, unknown> = {}) {
  return {
    conversation_id: 99,
    status: "answered",
    answer: "It creates a JWT access token.",
    evidence: [
      {
        chunk_id: 1,
        file_path: "app/core/security.py",
        start_line: 10,
        end_line: 20,
        language: "Python",
        chunk_type: "function",
        name: "create_access_token",
        chunk_text: "def create_access_token(subject):\n    return subject",
        score: 0.91,
        retrieval_sources: ["semantic"],
      },
    ],
    model: "mock-llm",
    ingestion_id: 1,
    input_tokens: 100,
    output_tokens: 20,
    ...overrides,
  };
}

async function askQuestion(user: ReturnType<typeof userEvent.setup>, text: string) {
  const input = screen.getByLabelText("Ask a question about this repository");
  await user.type(input, text);
  await user.click(screen.getByRole("button", { name: "Send" }));
}

describe("AskPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    routerReplace.mockClear();
    currentSearchParams = new URLSearchParams();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a clean empty state before the first question", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));

    renderWithQueryClient(<AskPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Ask anything about this repository"),
      ).toBeInTheDocument(),
    );
  });

  it("sends the first question as a new conversation (no conversation_id)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ask") return jsonResponse(200, answeredResponse());
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<AskPage />);
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled());

    await askQuestion(user, "How does auth work?");

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/repositories/1/ask",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ message: "How does auth work?" }),
        }),
      ),
    );
  });

  it("displays the user message and the assistant's answer with clear role distinction", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ask") return jsonResponse(200, answeredResponse());
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<AskPage />);
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled());
    await askQuestion(user, "How does auth work?");

    const log = await screen.findByRole("log", { name: "Conversation" });
    expect(within(log).getByText("How does auth work?")).toBeInTheDocument();
    expect(
      await within(log).findByText(/creates a JWT access token/),
    ).toBeInTheDocument();
  });

  it("shows evidence with file path, line range, and symbol for the answer", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ask") return jsonResponse(200, answeredResponse());
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<AskPage />);
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled());
    await askQuestion(user, "How does auth work?");

    expect(
      await screen.findByText("app/core/security.py:10-20"),
    ).toBeInTheDocument();
    expect(screen.getByText("create_access_token")).toBeInTheDocument();
    expect(await screen.findByText(/def create_access_token/)).toBeInTheDocument();
  });

  it("persists conversation_id across turns and reflects it in the URL", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ask") return jsonResponse(200, answeredResponse());
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<AskPage />);
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled());

    await askQuestion(user, "First question");
    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith("/repositories/1/ask?conversation=99"),
    );

    await askQuestion(user, "Second question");

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/repositories/1/ask",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            message: "Second question",
            conversation_id: 99,
          }),
        }),
      ),
    );
    // Only the first turn creates a conversation -- the URL isn't rewritten again.
    expect(routerReplace).toHaveBeenCalledTimes(1);
  });

  it("supports a multi-turn conversation, keeping every turn visible", async () => {
    let call = 0;
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ask") {
        call += 1;
        return jsonResponse(
          200,
          answeredResponse({ answer: call === 1 ? "First answer" : "Second answer" }),
        );
      }
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<AskPage />);
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled());

    await askQuestion(user, "Q1");
    await screen.findByText("First answer");
    await askQuestion(user, "Q2");
    await screen.findByText("Second answer");

    const log = screen.getByRole("log", { name: "Conversation" });
    expect(within(log).getByText("Q1")).toBeInTheDocument();
    expect(within(log).getByText("Q2")).toBeInTheDocument();
    expect(within(log).getByText("First answer")).toBeInTheDocument();
    expect(within(log).getByText("Second answer")).toBeInTheDocument();
  });

  it("renders a dedicated, non-error state for insufficient_evidence and lets the user ask again", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ask")
        return jsonResponse(200, {
          conversation_id: 99,
          status: "insufficient_evidence",
          answer: "I could not find enough evidence.",
          evidence: [],
          model: null,
          ingestion_id: 1,
          input_tokens: null,
          output_tokens: null,
        });
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<AskPage />);
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled());
    await askQuestion(user, "Something obscure");

    expect(
      await screen.findByText("Not enough evidence to answer"),
    ).toBeInTheDocument();
    expect(screen.queryByText("Something went wrong")).not.toBeInTheDocument();
    // The input is still usable for another question.
    expect(screen.getByLabelText(/ask a question/i)).toBeEnabled();
  });

  it.each([
    [404, "This repository or conversation could not be found."],
    [422, "Question too large for context"],
    [429, "The AI provider is rate-limited right now. Please try again shortly."],
    [502, "The AI provider is temporarily unavailable. Please try again."],
    [504, "The request timed out. Please try again."],
  ])("shows a friendly error for a %i response without crashing", async (status, expectedMessage) => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ask")
        return jsonResponse(status, { detail: "Question too large for context" });
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<AskPage />);
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled());
    await askQuestion(user, "A question");

    expect(await screen.findByText(expectedMessage)).toBeInTheDocument();
    // The user's own message is still shown even though the answer failed.
    expect(screen.getByText("A question")).toBeInTheDocument();
  });

  it("disables the send button and input while a request is in flight", async () => {
    let resolveFetch!: (value: Response) => void;
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ask") {
        return new Promise((resolve) => {
          resolveFetch = resolve;
        });
      }
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<AskPage />);
    await waitFor(() => expect(screen.getByLabelText(/ask a question/i)).toBeEnabled());
    await askQuestion(user, "A question");

    expect(screen.getByRole("button", { name: "Asking…" })).toBeDisabled();
    expect(screen.getByLabelText(/ask a question/i)).toBeDisabled();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();

    resolveFetch(jsonResponse(200, answeredResponse()));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send" })).toBeEnabled(),
    );
  });

  it("links back to the repository overview page", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));

    renderWithQueryClient(<AskPage />);

    const backLink = await screen.findByRole("link", { name: /my-repo/ });
    expect(backLink).toHaveAttribute("href", "/repositories/1");
  });
});
