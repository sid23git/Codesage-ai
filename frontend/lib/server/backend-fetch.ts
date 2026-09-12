import "server-only";

/**
 * Server-only helper for calling FastAPI directly (server-to-server).
 *
 * This is the ONLY place in the frontend that knows the backend's base URL
 * or talks to it directly. The browser never calls FastAPI -- it only ever
 * calls same-origin `/api/bff/*`, which uses this helper under the hood.
 * Because this is a server-to-server call, it is not subject to browser
 * CORS enforcement at all.
 */

const BACKEND_URL = process.env.BACKEND_URL ?? "http://localhost:8000";

export interface BackendFetchResult {
  status: number;
  body: unknown;
}

/**
 * Call `${BACKEND_URL}/api/v1/${path}`, optionally with a bearer token.
 * Returns the raw status + parsed JSON body (or `null` for empty bodies,
 * e.g. a 204) -- never throws for a non-2xx FastAPI response, since a 404,
 * 422, 429, 502, etc. is an entirely normal, expected outcome that callers
 * must pass through to the client, not swallow.
 */
export async function callBackend(
  path: string,
  init: {
    method?: string;
    token?: string;
    body?: unknown;
    searchParams?: URLSearchParams;
  } = {},
): Promise<BackendFetchResult> {
  const { method = "GET", token, body, searchParams } = init;

  const url = new URL(`/api/v1/${path}`.replace(/\/{2,}/g, "/"), BACKEND_URL);
  if (searchParams) {
    for (const [key, value] of searchParams) {
      url.searchParams.append(key, value);
    }
  }

  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  const response = await fetch(url, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
    // Never cache a backend call through this proxy -- every one of these
    // is either an authenticated, per-user read or a mutation.
    cache: "no-store",
  });

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  return { status: response.status, body: parsed };
}
