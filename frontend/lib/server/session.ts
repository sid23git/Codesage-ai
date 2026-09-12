import "server-only";

import { cookies } from "next/headers";

/**
 * Server-only session-cookie helpers.
 *
 * The cookie holds the FastAPI-issued JWT verbatim (opaque to this app) as an
 * httpOnly, Secure (in production), SameSite=Lax cookie. It is never read or
 * written from client-side code -- only from Route Handlers, which is the
 * only place Next.js allows `.set()`/`.delete()` to run.
 *
 * `maxAge` mirrors the backend's `ACCESS_TOKEN_EXPIRE_MINUTES` (default 24h).
 * There is no refresh-token endpoint on the backend, so this cookie's
 * lifetime IS the session's lifetime -- see SESSION_COOKIE_MAX_AGE_SECONDS.
 */

const COOKIE_NAME = process.env.SESSION_COOKIE_NAME ?? "cs_session";
const COOKIE_MAX_AGE_SECONDS = Number(
  process.env.SESSION_COOKIE_MAX_AGE_SECONDS ?? 86400,
);

export async function getSessionToken(): Promise<string | undefined> {
  const store = await cookies();
  return store.get(COOKIE_NAME)?.value;
}

export async function setSessionToken(token: string): Promise<void> {
  const store = await cookies();
  store.set(COOKIE_NAME, token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === "production",
    sameSite: "lax",
    path: "/",
    maxAge: COOKIE_MAX_AGE_SECONDS,
  });
}

export async function clearSessionToken(): Promise<void> {
  const store = await cookies();
  store.delete(COOKIE_NAME);
}
