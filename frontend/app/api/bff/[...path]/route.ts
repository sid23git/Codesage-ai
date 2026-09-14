import { NextRequest, NextResponse } from "next/server";

import { callBackend } from "@/lib/server/backend-fetch";
import { clearSessionToken, getSessionToken } from "@/lib/server/session";

/**
 * Generic BFF proxy for every backend endpoint except auth/login,
 * auth/register, and auth/logout (which are special-cased next to this
 * file, since they translate the token <-> cookie rather than just
 * forwarding it).
 *
 * This route intentionally contains NO business logic: it reads the
 * session cookie, attaches it as `Authorization: Bearer <token>`, forwards
 * the request to FastAPI, and passes the response straight back. Keeping
 * it this thin means the frontend never re-implements backend behavior,
 * and adding a new backend endpoint never requires a new frontend file.
 */

function isSafePathSegment(segment: string): boolean {
  // Reject empty/"."/".." segments outright -- defense in depth against
  // path traversal escaping the intended /api/v1/* namespace on the
  // backend host. (Every real backend route requires its own bearer-token
  // auth regardless, so this is a hardening measure, not the only thing
  // standing between a client and an unauthorized resource.)
  return segment.length > 0 && segment !== "." && segment !== "..";
}

async function handle(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await context.params;

  if (path.length === 0 || !path.every(isSafePathSegment)) {
    return NextResponse.json({ error: { detail: "Invalid path" } }, { status: 400 });
  }

  const token = await getSessionToken();

  let body: unknown;
  if (request.method !== "GET" && request.method !== "HEAD") {
    const text = await request.text();
    if (text) {
      try {
        body = JSON.parse(text);
      } catch {
        body = text;
      }
    }
  }

  let result: Awaited<ReturnType<typeof callBackend>>;
  try {
    result = await callBackend(path.join("/"), {
      method: request.method,
      token,
      body,
      searchParams: request.nextUrl.searchParams,
    });
  } catch (error) {
    // The backend being unreachable (down, restarting, DNS/network
    // failure) is the single most common real-world failure mode of a
    // split frontend/backend deployment -- without this boundary, that
    // `fetch` rejection propagates as an unhandled exception, and Next.js
    // returns a bare, non-JSON 500 that the client's typed error handling
    // (which expects a JSON `{ "detail": ... }` body) can't parse. A 502
    // here is both accurate (the backend, not this proxy, is at fault)
    // and lets the existing retry-eligible ErrorState UI engage.
    console.error("BFF proxy: backend request failed", error);
    return NextResponse.json(
      { detail: "The server is temporarily unavailable. Please try again." },
      { status: 502 },
    );
  }

  if (result.status === 401 && token) {
    // The token FastAPI holds is invalid/expired -- clear it so the client
    // is prompted to sign in again rather than retrying with a dead cookie.
    await clearSessionToken();
  }

  return NextResponse.json(result.body, { status: result.status });
}

export {
  handle as GET,
  handle as POST,
  handle as PUT,
  handle as PATCH,
  handle as DELETE,
};
