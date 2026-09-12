import { NextRequest } from "next/server";
import { describe, expect, it } from "vitest";

import { proxy } from "@/proxy";

function requestFor(path: string, cookie?: string) {
  return new NextRequest(new URL(path, "http://localhost:3000"), {
    headers: cookie ? { cookie: `cs_session=${cookie}` } : {},
  });
}

describe("proxy (route protection gate)", () => {
  it("redirects an unauthenticated request to a protected route to /login", () => {
    const response = proxy(requestFor("/dashboard"));
    expect(response.status).toBe(307);
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("from")).toBe("/dashboard");
  });

  it("redirects an unauthenticated request to a repository page to /login", () => {
    const response = proxy(requestFor("/repositories/42"));
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("from")).toBe("/repositories/42");
  });

  it("allows an authenticated request to a protected route through", () => {
    const response = proxy(requestFor("/dashboard", "valid-token"));
    expect(response.headers.get("location")).toBeNull();
  });

  it("allows an unauthenticated request to the public landing page through", () => {
    const response = proxy(requestFor("/"));
    expect(response.headers.get("location")).toBeNull();
  });

  it("allows an unauthenticated request to /login through", () => {
    const response = proxy(requestFor("/login"));
    expect(response.headers.get("location")).toBeNull();
  });

  it("redirects an already-authenticated request away from /login to /dashboard", () => {
    const response = proxy(requestFor("/login", "valid-token"));
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/dashboard");
  });

  it("redirects an already-authenticated request away from /register to /dashboard", () => {
    const response = proxy(requestFor("/register", "valid-token"));
    const location = new URL(response.headers.get("location")!);
    expect(location.pathname).toBe("/dashboard");
  });

  it("never decodes or validates the cookie's contents -- presence alone is enough to pass", () => {
    // An obviously-garbage token still passes the gate; real validity is
    // decided only by FastAPI's own 401s (handled by the BFF proxy).
    const response = proxy(requestFor("/dashboard", "not-a-real-jwt"));
    expect(response.headers.get("location")).toBeNull();
  });
});
