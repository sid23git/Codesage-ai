import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockCallBackend = vi.fn();
const mockGetSessionToken = vi.fn();
const mockClearSessionToken = vi.fn();

vi.mock("@/lib/server/backend-fetch", () => ({
  callBackend: (...args: unknown[]) => mockCallBackend(...args),
}));
vi.mock("@/lib/server/session", () => ({
  getSessionToken: () => mockGetSessionToken(),
  clearSessionToken: () => mockClearSessionToken(),
}));

// Imported after the mocks above so the route module picks up the mocked
// session/backend-fetch modules rather than the real (next/headers-backed,
// request-scope-dependent) implementations.
const { GET, POST } = await import("@/app/api/bff/[...path]/route");

function requestFor(
  path: string,
  init?: ConstructorParameters<typeof NextRequest>[1],
): NextRequest {
  return new NextRequest(new URL(`http://localhost:3000/api/bff/${path}`), init);
}

function contextFor(path: string[]) {
  return { params: Promise.resolve({ path }) };
}

describe("BFF generic proxy ([...path]/route.ts)", () => {
  beforeEach(() => {
    mockCallBackend.mockReset();
    mockGetSessionToken.mockReset().mockResolvedValue("a-session-token");
    mockClearSessionToken.mockReset();
  });

  it("passes through a successful backend response unchanged", async () => {
    mockCallBackend.mockResolvedValue({ status: 200, body: { id: 1 } });

    const response = await GET(
      requestFor("repositories/1"),
      contextFor(["repositories", "1"]),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ id: 1 });
  });

  it("returns a parseable 502 when the backend is unreachable, instead of throwing", async () => {
    mockCallBackend.mockRejectedValue(new Error("fetch failed: ECONNREFUSED"));

    const response = await GET(
      requestFor("repositories"),
      contextFor(["repositories"]),
    );

    expect(response.status).toBe(502);
    const body = await response.json();
    // Same { detail: string } shape every other backend error already
    // uses, so the client's existing typed-error handling parses it.
    expect(typeof body.detail).toBe("string");
    expect(body.detail).toMatch(/temporarily unavailable/i);
  });

  it("clears the session cookie when the backend reports 401", async () => {
    mockCallBackend.mockResolvedValue({
      status: 401,
      body: { detail: "Could not validate credentials" },
    });

    const response = await GET(
      requestFor("repositories"),
      contextFor(["repositories"]),
    );

    expect(response.status).toBe(401);
    expect(mockClearSessionToken).toHaveBeenCalledTimes(1);
  });

  it("does not clear the cookie for a 401 when there was no token to begin with", async () => {
    mockGetSessionToken.mockResolvedValue(undefined);
    mockCallBackend.mockResolvedValue({ status: 401, body: { detail: "no token" } });

    await GET(requestFor("repositories"), contextFor(["repositories"]));

    expect(mockClearSessionToken).not.toHaveBeenCalled();
  });

  it("rejects a path-traversal segment before ever calling the backend", async () => {
    const response = await GET(
      requestFor("repositories/..%2Fsecret"),
      contextFor(["repositories", "..", "secret"]),
    );

    expect(response.status).toBe(400);
    expect(mockCallBackend).not.toHaveBeenCalled();
  });

  it("rejects an empty path before ever calling the backend", async () => {
    const response = await GET(requestFor(""), contextFor([]));

    expect(response.status).toBe(400);
    expect(mockCallBackend).not.toHaveBeenCalled();
  });

  it("forwards a JSON request body to callBackend", async () => {
    mockCallBackend.mockResolvedValue({ status: 201, body: { id: 5 } });

    const response = await POST(
      requestFor("repositories", {
        method: "POST",
        body: JSON.stringify({ name: "my-repo" }),
      }),
      contextFor(["repositories"]),
    );

    expect(response.status).toBe(201);
    expect(mockCallBackend).toHaveBeenCalledWith(
      "repositories",
      expect.objectContaining({
        method: "POST",
        token: "a-session-token",
        body: { name: "my-repo" },
      }),
    );
  });
});
