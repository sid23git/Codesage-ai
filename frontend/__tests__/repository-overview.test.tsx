import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RepositoryOverviewPage from "@/app/(app)/repositories/[id]/page";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "1" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const repo = {
  id: 1,
  owner_id: 1,
  name: "my-repo",
  full_name: "octocat/my-repo",
  github_url: "https://github.com/octocat/my-repo",
  description: "A test repo",
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

describe("RepositoryOverviewPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows repository identity, status, and a not-yet-ingested prompt", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ingestion")
        return jsonResponse(404, { detail: "Ingestion record not found for this repository" });
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() => expect(screen.getByText("my-repo")).toBeInTheDocument());
    expect(screen.getByText("A test repo")).toBeInTheDocument();
    expect(
      screen.getByText(/hasn't been ingested yet/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start ingestion" })).toBeInTheDocument();
  });

  it("shows completed ingestion metrics and a re-ingest action", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ingestion")
        return jsonResponse(200, {
          id: 1,
          repository_id: 1,
          status: "completed",
          commit_sha: "abc",
          file_count: 42,
          total_size_bytes: 1000,
          total_lines: 1234,
          primary_language: "Python",
          language_stats: null,
          directory_summary: null,
          file_catalog: null,
          error_message: null,
          started_at: "2026-01-01T00:00:00Z",
          completed_at: "2026-01-01T00:05:00Z",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:05:00Z",
        });
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() => expect(screen.getByText("42")).toBeInTheDocument());
    expect(screen.getByText("1,234")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-ingest" })).toBeInTheDocument();
  });

  it("shows the failure reason and a retry action for a failed ingestion", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ingestion")
        return jsonResponse(200, {
          id: 1,
          repository_id: 1,
          status: "failed",
          commit_sha: null,
          file_count: 0,
          total_size_bytes: 0,
          total_lines: 0,
          primary_language: null,
          language_stats: null,
          directory_summary: null,
          file_catalog: null,
          error_message: "Repository archive exceeded the size limit",
          started_at: "2026-01-01T00:00:00Z",
          completed_at: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        });
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() =>
      expect(
        screen.getByText("Repository archive exceeded the size limit"),
      ).toBeInTheDocument(),
    );
    const retryButton = screen.getByRole("button", { name: "Retry ingestion" });
    expect(retryButton).toBeInTheDocument();

    // Retry actually calls POST /ingest.
    const user = userEvent.setup();
    await user.click(retryButton);
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/repositories/1/ingest",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("syncs the repository from GitHub successfully", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(
      async (url: string) => {
        const path = routeFor(url);
        if (path === "repositories/1/sync")
          return jsonResponse(200, { ...repo, status: "ready", stars: 10 });
        if (path === "repositories/1")
          return jsonResponse(200, repo);
        if (path === "repositories/1/ingestion")
          return jsonResponse(404, { detail: "not found" });
        return jsonResponse(404, { detail: "not found" });
      },
    );

    const user = userEvent.setup();
    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sync from GitHub" })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "Sync from GitHub" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/repositories/1/sync",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("surfaces a sync failure (e.g. GitHub rate limit) via toast without crashing", async () => {
    const { toast } = await import("sonner");
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ingestion")
        return jsonResponse(404, { detail: "not found" });
      if (path === "repositories/1/sync")
        return jsonResponse(429, { detail: "GitHub rate limit exceeded" });
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sync from GitHub" })).toBeInTheDocument(),
    );
    await user.click(screen.getByRole("button", { name: "Sync from GitHub" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("GitHub rate limit exceeded"),
    );
  });
});
