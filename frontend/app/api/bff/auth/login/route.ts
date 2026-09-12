import { NextResponse } from "next/server";

import { callBackend } from "@/lib/server/backend-fetch";
import { setSessionToken } from "@/lib/server/session";

/**
 * BFF login: calls FastAPI's /auth/login, then translates the JSON
 * access_token it returns into an httpOnly session cookie. The raw token
 * is never sent back to the browser -- the response body here only ever
 * confirms success/failure, never the token itself.
 */
export async function POST(request: Request) {
  const credentials = await request.json();

  const result = await callBackend("auth/login", {
    method: "POST",
    body: credentials,
  });

  if (result.status !== 200) {
    return NextResponse.json(
      { error: result.body ?? { detail: "Login failed" } },
      { status: result.status },
    );
  }

  const body = result.body as { access_token?: string };
  if (!body.access_token) {
    return NextResponse.json(
      { error: { detail: "Backend did not return an access token" } },
      { status: 502 },
    );
  }

  await setSessionToken(body.access_token);
  return NextResponse.json({ ok: true });
}
