import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NewRepositoryPage from "@/app/(app)/repositories/new/page";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

async function fillValidForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Name"), "my-repo");
  await user.type(
    screen.getByLabelText("GitHub URL"),
    "https://github.com/octocat/Hello-World",
  );
}

describe("NewRepositoryPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    push.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("rejects an invalid GitHub URL client-side without calling the API", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<NewRepositoryPage />);

    await user.type(screen.getByLabelText("Name"), "my-repo");
    await user.type(screen.getByLabelText("GitHub URL"), "not-a-url");
    await user.click(screen.getByRole("button", { name: "Add repository" }));

    expect(
      await screen.findByText(/must be a github repository url/i),
    ).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("creates a repository and redirects to its overview page on success", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(201, {
        id: 7,
        owner_id: 1,
        name: "my-repo",
        full_name: "octocat/Hello-World",
        github_url: "https://github.com/octocat/Hello-World",
        description: null,
        primary_language: null,
        status: "pending",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<NewRepositoryPage />);

    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Add repository" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/repositories/7"));
  });

  it("shows an inline error for a duplicate repository (409)", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(409, { detail: "Repository already connected" }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<NewRepositoryPage />);

    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Add repository" }));

    expect(
      await screen.findByText("This repository is already connected."),
    ).toBeInTheDocument();
    expect(push).not.toHaveBeenCalled();
  });

  it("shows the backend's validation message for a 422 response", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(422, { detail: "Hostname must be github.com" }),
    );
    const user = userEvent.setup();
    renderWithQueryClient(<NewRepositoryPage />);

    await fillValidForm(user);
    await user.click(screen.getByRole("button", { name: "Add repository" }));

    expect(
      await screen.findByText("Hostname must be github.com"),
    ).toBeInTheDocument();
  });

  it("does not submit a second request while one is already in flight", async () => {
    let resolveFetch!: (value: Response) => void;
    (fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );
    const user = userEvent.setup();
    const { container } = renderWithQueryClient(<NewRepositoryPage />);

    await fillValidForm(user);
    const form = container.querySelector("form")!;
    // Fire submit twice back-to-back, simulating a rapid double
    // Enter/click before the button's disabled state can visually update.
    form.requestSubmit();
    form.requestSubmit();

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    resolveFetch(
      jsonResponse(201, {
        id: 1,
        owner_id: 1,
        name: "my-repo",
        full_name: "octocat/Hello-World",
        github_url: "https://github.com/octocat/Hello-World",
        description: null,
        primary_language: null,
        status: "pending",
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      }),
    );
  });
});
