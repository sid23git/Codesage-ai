import { screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import DashboardPage from "@/app/(app)/dashboard/page";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a loading state before data arrives", () => {
    (fetch as ReturnType<typeof vi.fn>).mockReturnValue(new Promise(() => {}));

    renderWithQueryClient(<DashboardPage />);

    expect(screen.getByRole("status", { name: "Loading" })).toBeInTheDocument();
  });

  it("shows the empty state with a call-to-action when there are no repositories", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, []));

    renderWithQueryClient(<DashboardPage />);

    await waitFor(() =>
      expect(screen.getByText("No repositories yet")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("link", { name: "Connect a repository" }),
    ).toHaveAttribute("href", "/repositories/new");
  });

  it("renders repository cards with name, URL, language, and status", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(200, [
        {
          id: 1,
          owner_id: 1,
          name: "my-repo",
          full_name: "octocat/my-repo",
          github_url: "https://github.com/octocat/my-repo",
          description: null,
          primary_language: "Python",
          status: "ready",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-02T00:00:00Z",
        },
      ]),
    );

    renderWithQueryClient(<DashboardPage />);

    await waitFor(() => expect(screen.getByText("my-repo")).toBeInTheDocument());
    expect(
      screen.getByText("https://github.com/octocat/my-repo"),
    ).toBeInTheDocument();
    expect(screen.getByText("Python")).toBeInTheDocument();
    expect(screen.getByText("ready")).toBeInTheDocument();
  });

  it("shows an error state with a retry action when the request fails", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(502, { detail: "Upstream failure" }),
    );

    renderWithQueryClient(<DashboardPage />);

    await waitFor(() =>
      expect(screen.getByText("Something went wrong")).toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });
});
