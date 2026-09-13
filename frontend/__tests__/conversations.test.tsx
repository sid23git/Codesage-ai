import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ConversationsPage from "@/app/(app)/repositories/[id]/conversations/page";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

let currentId = "1";
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: currentId }),
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

describe("ConversationsPage", () => {
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

    renderWithQueryClient(<ConversationsPage />);

    expect(await screen.findByText("Repository not found")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("shows a loading state before conversations arrive", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations") return new Promise(() => {});
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationsPage />);

    await waitFor(() => expect(screen.getByText("Conversation history")).toBeInTheDocument());
    expect(screen.getAllByRole("status", { name: "Loading" }).length).toBeGreaterThan(0);
  });

  it("shows an empty state with a call-to-action when there are no conversations", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations") return jsonResponse(200, []);
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationsPage />);

    await waitFor(() => expect(screen.getByText("No conversations yet")).toBeInTheDocument());
    expect(
      screen.getByRole("link", { name: "Ask a question" }),
    ).toHaveAttribute("href", "/repositories/1/ask");
  });

  it("renders conversations with title and updated time, most recent first as provided by the backend", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations")
        return jsonResponse(200, [
          {
            id: 2,
            repository_id: 1,
            title: "Auth flow questions",
            created_at: "2026-01-02T00:00:00Z",
            updated_at: "2026-01-03T00:00:00Z",
          },
          {
            id: 1,
            repository_id: 1,
            title: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          },
        ]);
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationsPage />);

    await waitFor(() => expect(screen.getByText("Auth flow questions")).toBeInTheDocument());
    // No title -- falls back to a stable, non-invented label using the real id.
    expect(screen.getByText("Conversation #1")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Auth flow questions/ }),
    ).toHaveAttribute("href", "/repositories/1/conversations/2");
  });

  it("shows an error state with retry when the conversations request fails", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/conversations")
        return jsonResponse(502, { detail: "Upstream failure" });
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<ConversationsPage />);

    await waitFor(() => expect(screen.getByText("Something went wrong")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
