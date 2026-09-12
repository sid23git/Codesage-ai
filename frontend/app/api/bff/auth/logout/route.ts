import { NextResponse } from "next/server";

import { clearSessionToken } from "@/lib/server/session";

/**
 * BFF logout: clears the session cookie. There is no backend logout
 * endpoint to call -- the FastAPI JWT is stateless, so "logging out" is
 * entirely a matter of the browser no longer holding a usable session.
 */
export async function POST() {
  await clearSessionToken();
  return NextResponse.json({ ok: true });
}
