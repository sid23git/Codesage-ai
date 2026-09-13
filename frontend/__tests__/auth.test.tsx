import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import LoginPage from "@/app/(auth)/login/page";
import RegisterPage from "@/app/(auth)/register/page";
import { jsonResponse, renderWithQueryClient } from "@/test-utils";

const routerReplace = vi.fn();
let currentSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: routerReplace, push: vi.fn() }),
  useSearchParams: () => currentSearchParams,
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function routeFor(url: string) {
  return url.replace(/^\/api\/bff\//, "");
}

describe("LoginPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    routerReplace.mockClear();
    currentSearchParams = new URLSearchParams();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requires an email and password before submitting", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<LoginPage />);

    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(screen.getByText("Password is required.")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("signs in and redirects to /dashboard by default", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "auth/login") return jsonResponse(200, { ok: true });
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<LoginPage />);

    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/bff/auth/login",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ email: "user@example.com", password: "correct-password" }),
        }),
      ),
    );
    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/dashboard"));
  });

  it("redirects back to the originally-requested page after signing in", async () => {
    currentSearchParams = new URLSearchParams({ from: "/repositories/42" });
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(jsonResponse(200, { ok: true }));

    const user = userEvent.setup();
    renderWithQueryClient(<LoginPage />);

    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Password"), "correct-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(routerReplace).toHaveBeenCalledWith("/repositories/42"),
    );
  });

  it("shows a clear message when arriving after an expired session", () => {
    currentSearchParams = new URLSearchParams({ reason: "expired" });

    renderWithQueryClient(<LoginPage />);

    expect(
      screen.getByText("Your session expired. Please sign in again."),
    ).toBeInTheDocument();
  });

  it("shows a friendly error toast for invalid credentials without crashing", async () => {
    const { toast } = await import("sonner");
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(401, { error: { detail: "Incorrect email or password" } }),
    );

    const user = userEvent.setup();
    renderWithQueryClient(<LoginPage />);

    await user.type(screen.getByLabelText("Email"), "user@example.com");
    await user.type(screen.getByLabelText("Password"), "wrong-password");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Incorrect email or password"),
    );
    // Failed sign-in never navigates anywhere.
    expect(routerReplace).not.toHaveBeenCalled();
  });

  it("links to the registration page", () => {
    renderWithQueryClient(<LoginPage />);

    expect(screen.getByRole("link", { name: "Register" })).toHaveAttribute(
      "href",
      "/register",
    );
  });
});

describe("RegisterPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
    routerReplace.mockClear();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requires a valid email and an 8+ character password", async () => {
    const user = userEvent.setup();
    renderWithQueryClient(<RegisterPage />);

    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
    expect(
      screen.getByText("Password must be at least 8 characters."),
    ).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("registers, auto-logs in, and lands straight in the dashboard", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "auth/register") return jsonResponse(200, { ok: true, autoLogin: true });
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<RegisterPage />);

    await user.type(screen.getByLabelText("Email"), "new-user@example.com");
    await user.type(screen.getByLabelText("Password"), "a-strong-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(routerReplace).toHaveBeenCalledWith("/dashboard"));
  });

  it("falls back to the login page when auto-login didn't happen", async () => {
    const { toast } = await import("sonner");
    (fetch as ReturnType<typeof vi.fn>).mockImplementation(async (url: string) => {
      const path = routeFor(url);
      if (path === "auth/register") return jsonResponse(200, { ok: true, autoLogin: false });
      return jsonResponse(404, { detail: "not found" });
    });

    const user = userEvent.setup();
    renderWithQueryClient(<RegisterPage />);

    await user.type(screen.getByLabelText("Email"), "new-user@example.com");
    await user.type(screen.getByLabelText("Password"), "a-strong-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Account created. Please sign in."),
    );
    expect(routerReplace).toHaveBeenCalledWith("/login");
  });

  it("shows a friendly error toast when the email is already registered", async () => {
    const { toast } = await import("sonner");
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(
      jsonResponse(409, { error: { detail: "An account with this email already exists." } }),
    );

    const user = userEvent.setup();
    renderWithQueryClient(<RegisterPage />);

    await user.type(screen.getByLabelText("Email"), "existing@example.com");
    await user.type(screen.getByLabelText("Password"), "a-strong-password");
    await user.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("An account with this email already exists."),
    );
    expect(routerReplace).not.toHaveBeenCalled();
  });

  it("links to the login page", () => {
    renderWithQueryClient(<RegisterPage />);

    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });
});
