import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import RepositoryOverviewPage from "@/app/(app)/repositories/[id]/page";
import { QueryProvider } from "@/lib/query/provider";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

const routerReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "1" }),
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
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
    routerReplace.mockClear();
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

  it("shows a loading state before the repository loads", () => {
    (fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));

    renderWithQueryClient(<RepositoryOverviewPage />);

    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  });

  it("shows a not-found state for a repository that doesn't exist or isn't owned by the user", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(404, { detail: "Repository not found" }),
    );

    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() =>
      expect(screen.getByText("Repository not found")).toBeInTheDocument(),
    );
  });

  it("shows an in-progress state (no fabricated percentage) while ingestion is running", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ingestion")
        return jsonResponse(200, {
          id: 1,
          repository_id: 1,
          status: "ingesting",
          commit_sha: "abc",
          file_count: 0,
          total_size_bytes: 0,
          total_lines: 0,
          primary_language: null,
          language_stats: null,
          directory_summary: null,
          file_catalog: null,
          error_message: null,
          started_at: "2026-01-01T00:00:00Z",
          completed_at: null,
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        });
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() =>
      expect(screen.getByText(/downloading and analyzing/i)).toBeInTheDocument(),
    );
    // No "%" or "progress" fabrication anywhere in the panel.
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
  });

  it("renders ingestion history, most recent first, capped for readability", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ingestion")
        return jsonResponse(404, { detail: "not found" });
      if (path === "repositories/1/ingestions") {
        const runs = Array.from({ length: 7 }).map((_, i) => ({
          id: 7 - i,
          repository_id: 1,
          status: i === 3 ? "failed" : "completed",
          commit_sha: "abc",
          file_count: 10,
          total_size_bytes: 100,
          total_lines: 200,
          primary_language: "Python",
          language_stats: null,
          error_message: i === 3 ? "Timed out" : null,
          started_at: "2026-01-01T00:00:00Z",
          completed_at: "2026-01-01T00:05:00Z",
          created_at: `2026-01-0${7 - i}T00:00:00Z`,
          updated_at: `2026-01-0${7 - i}T00:00:00Z`,
        }));
        return jsonResponse(200, runs);
      }
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() =>
      expect(screen.getByText("Ingestion history")).toBeInTheDocument(),
    );
    // 7 runs returned, only 5 shown, with a note about the rest.
    expect(screen.getByText("2 earlier runs not shown.")).toBeInTheDocument();
    expect(screen.getByText("Timed out")).toBeInTheDocument();
  });

  it("invalidates and refetches ingestion history after starting a new ingestion", async () => {
    let ingestionsCallCount = 0;
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(
      async (url: string) => {
        const path = routeFor(url);
        if (path === "repositories/1") return jsonResponse(200, repo);
        if (path === "repositories/1/ingestion")
          return jsonResponse(404, { detail: "not found" });
        if (path === "repositories/1/ingest")
          return jsonResponse(200, {
            id: 1,
            repository_id: 1,
            status: "ingesting",
            commit_sha: null,
            file_count: 0,
            total_size_bytes: 0,
            total_lines: 0,
            primary_language: null,
            language_stats: null,
            directory_summary: null,
            file_catalog: null,
            error_message: null,
            started_at: "2026-01-01T00:00:00Z",
            completed_at: null,
            created_at: "2026-01-01T00:00:00Z",
            updated_at: "2026-01-01T00:00:00Z",
          });
        if (path === "repositories/1/ingestions") {
          ingestionsCallCount += 1;
          return jsonResponse(200, []);
        }
        return jsonResponse(404, { detail: "not found" });
      },
    );

    const user = userEvent.setup();
    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Start ingestion" })).toBeInTheDocument(),
    );
    const callsBeforeStart = ingestionsCallCount;
    await user.click(screen.getByRole("button", { name: "Start ingestion" }));

    // The history query key was invalidated by useIngestRepository's
    // onSuccess, triggering a refetch beyond the initial mount fetch.
    await waitFor(() => expect(ingestionsCallCount).toBeGreaterThan(callsBeforeStart));
  });

  it("links the GitHub URL out to the actual repository", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<RepositoryOverviewPage />);

    await waitFor(() => expect(screen.getByText("my-repo")).toBeInTheDocument());
    // The GitHub URL link is present and points at the real repository.
    expect(screen.getByRole("link", { name: repo.github_url })).toHaveAttribute(
      "href",
      repo.github_url,
    );
  });

  it("always shows a History link, even before ingestion completes", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "repositories/1") return jsonResponse(200, repo);
      if (path === "repositories/1/ingestion")
        return jsonResponse(404, { detail: "Ingestion record not found for this repository" });
      return jsonResponse(404, { detail: "not found" });
    });

    renderWithQueryClient(<RepositoryOverviewPage />);

    const historyLink = await screen.findByRole("link", { name: "History" });
    expect(historyLink).toHaveAttribute("href", "/repositories/1/conversations");
    // Unlike History, Ask/Explain/Review stay disabled until ingestion completes.
    expect(screen.getByText("Ask").closest("button")).toBeDisabled();
  });

  it("redirects to /login when the session has expired (401 from the backend)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(401, { detail: "Could not validate credentials" }),
    );

    // Rendered inside the app's real QueryProvider (not the bare test
    // helper) so its global 401 -> redirect wiring (lib/query/provider.tsx,
    // registered in Phase 0) is actually exercised end-to-end here.
    render(
      <QueryProvider>
        <RepositoryOverviewPage />
      </QueryProvider>,
    );

    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith("/login?reason=expired"),
    );
  });
});
