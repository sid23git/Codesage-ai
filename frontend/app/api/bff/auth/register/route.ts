import { NextResponse } from "next/server";

import { callBackend } from "@/lib/server/backend-fetch";
import { setSessionToken } from "@/lib/server/session";

/**
 * BFF register: calls FastAPI's /auth/register, then immediately chains a
 * login call with the same credentials so a newly-registered user lands in
 * the app already signed in, rather than being sent back to a login form.
 * (Plan Section 4, step 8 -- a default choice, easy to reverse later.)
 */
export async function POST(request: Request) {
  const credentials = await request.json();

  const registerResult = await callBackend("auth/register", {
    method: "POST",
    body: credentials,
  });

  if (registerResult.status !== 201) {
    return NextResponse.json(
      { error: registerResult.body ?? { detail: "Registration failed" } },
      { status: registerResult.status },
    );
  }

  const loginResult = await callBackend("auth/login", {
    method: "POST",
    body: credentials,
  });

  if (loginResult.status !== 200) {
    // Registration succeeded but the auto-login didn't -- still a success
    // from the user's perspective, just send them to the login page.
    return NextResponse.json({ ok: true, autoLogin: false });
  }

  const body = loginResult.body as { access_token?: string };
  if (body.access_token) {
    await setSessionToken(body.access_token);
  }
  return NextResponse.json({ ok: true, autoLogin: Boolean(body.access_token) });
}
