import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConversationDetailPage from "@/app/(app)/repositories/[id]/conversations/[cid]/page";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

vi.mock("shiki", () => ({
  codeToHtml: vi.fn(async (code: string) => `<pre><code>${code}</code></pre>`),
}));
let currentId = "1";
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: currentId, cid: "5" }),
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

function conversationDetail(overrides: Record<string, unknown> = {}) {
  return {
    id: 5,
    repository_id: 1,
    title: "Auth flow questions",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:05:00Z",
    messages: [
      {
        id: 1,
        role: "user",
        content: "How does auth work?",
        evidence: null,
        model: null,
        input_tokens: null,
        output_tokens: null,
        created_at: "2026-01-01T00:00:00Z",
      },
      {
        id: 2,
        role: "assistant",
        content: "It **creates a JWT** access token.",
        evidence: [
          {
            chunk_id: 1,
            file_path: "app/core/security.py",
            start_line: 5,
            end_line: 15,
            language: "Python",
            name: "create_access_token",
            score: 0.9,
            snippet: "def create_access_token(subject):\n    return subject",
          },
        ],
        model: "mock-llm",
        input_tokens: 50,
        output_tokens: 10,
        created_at: "2026-01-01T00:01:00Z",
      },
    ],
    ...overrides,
  };
}

describe("ConversationDetailPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    currentId = "1";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a not-found state (not a blank page) for a malformed repository id in the URL", async () => {
    currentId = "not-a-number";
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, repo));

    renderWithQueryClient(<ConversationDetailPage />);

    expect(await screen.findByText("Repository not found")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows a loading state before the conversation loads", () => {
    (fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));

    renderWithQueryClient(<ConversationDetailPage />);

    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  });

  it("renders messages chronologically with clear user/assistant distinction, Markdown, and evidence", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations/5")
        return jsonResponse(200, conversationDetail());
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationDetailPage />);

    await waitFor(() => expect(screen.getByText("Auth flow questions")).toBeInTheDocument());

    // Chronological order: the question appears before the answer.
    const bodyText = document.body.textContent ?? "";
    expect(bodyText.indexOf("How does auth work?")).toBeLessThan(
      bodyText.indexOf("creates a JWT"),
    );

    // Markdown was rendered (bold), not shown as literal asterisks.
    expect(screen.getByText("creates a JWT")).toBeInTheDocument();
    expect(screen.queryByText(/\*\*creates a JWT\*\*/)).not.toBeInTheDocument();

    // Evidence is visible, using the same shared citation component.
    expect(screen.getByText("app/core/security.py:5-15")).toBeInTheDocument();
    expect(screen.getByText("create_access_token")).toBeInTheDocument();
  });

  it("shows a Continue conversation link into the Ask page with the conversation_id", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations/5")
        return jsonResponse(200, conversationDetail());
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationDetailPage />);

    const continueLink = await screen.findByRole("link", { name: "Continue conversation" });
    expect(continueLink).toHaveAttribute("href", "/repositories/1/ask?conversation=5");
  });

  it("shows an empty state for a conversation with no messages", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations/5")
        return jsonResponse(200, conversationDetail({ messages: [] }));
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationDetailPage />);

    expect(await screen.findByText("No messages yet")).toBeInTheDocument();
  });

  it("shows a not-found state for a conversation that doesn't exist or isn't owned by the user", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations/5")
        return jsonResponse(404, { detail: "Conversation not found" });
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationDetailPage />);

    expect(await screen.findByText("Conversation not found")).toBeInTheDocument();
  });

  it("does not leak another user's repository (repository ownership 404 takes precedence)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(404, { detail: "Repository not found" }),
    );

    renderWithQueryClient(<ConversationDetailPage />);

    expect(await screen.findByText("Repository not found")).toBeInTheDocument();
  });

  it.each([[429], [502], [504]])(
    "shows an error state with retry for a %i backend response",
    async (status) => {
      (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
        const path = routeFor(url);
        if (path === "repositories/1") return jsonResponse(200, repo);
        if (path === "repositories/1/conversations/5")
          return jsonResponse(status, { detail: "Upstream failure" });
        return jsonResponse(404, { detail: "not found" });
      });

      renderWithQueryClient(<ConversationDetailPage />);

      expect(await screen.findByText("Something went wrong")).toBeInTheDocument();
    },
  );
});

describe("ConversationDetailPage evidence provenance", () => {
  it("never implies historical evidence belongs to the current ingestion", async () => {
    vi.stubGlobal("fetch", vi.fn());
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations/5")
        return jsonResponse(200, conversationDetail());
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationDetailPage />);
    await screen.findByText("app/core/security.py:5-15");

    expect(screen.queryByText(/current ingestion/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/latest ingestion/i)).not.toBeInTheDocument();
    vi.unstubAllGlobals();
  });
});

describe("ConversationDetailPage with an unauthenticated session", () => {
  it("does not crash when the backend returns 401 (global handler takes over)", async () => {
    vi.stubGlobal("fetch", vi.fn());
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(401, { detail: "Could not validate credentials" }),
    );

    renderWithQueryClient(<ConversationDetailPage />);

    await waitFor(() =>
      expect(screen.getByText("Something went wrong")).toBeInTheDocument(),
    );
    vi.unstubAllGlobals();
  });
});
