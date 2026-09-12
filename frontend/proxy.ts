import { NextRequest, NextResponse } from "next/server";

/**
 * Route protection gate (Next.js 16 renamed `middleware.ts` to `proxy.ts` --
 * same mechanism, new file name).
 *
 * This is a PRESENCE-ONLY check: it only asks "is there a session cookie at
 * all?", never decodes or validates the JWT inside it. Actual validity is
 * always decided by FastAPI's own 401 responses (handled by the BFF proxy,
 * which clears the cookie when that happens) -- duplicating JWT validation
 * here would duplicate backend auth logic, which this plan explicitly
 * avoids.
 */

// "/" is a public landing page -- visible regardless of auth state.
const PUBLIC_ROUTES = ["/", "/login", "/register"];
// Pure auth forms -- redirect away from these if already signed in, since
// showing a login/register form to an authenticated user is never useful.
const AUTH_FORM_ROUTES = ["/login", "/register"];
const SESSION_COOKIE_NAME = process.env.SESSION_COOKIE_NAME ?? "cs_session";

export function proxy(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl;
  const hasSession = Boolean(
    request.cookies.get(SESSION_COOKIE_NAME)?.value,
  );
  const isPublicRoute = PUBLIC_ROUTES.includes(pathname);

  if (!isPublicRoute && !hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("from", pathname);
    return NextResponse.redirect(loginUrl);
  }

  if (AUTH_FORM_ROUTES.includes(pathname) && hasSession) {
    return NextResponse.redirect(new URL("/dashboard", request.url));
  }

  return NextResponse.next();
}

export const config = {
  // Run on every page route except Next internals, static files, and the
  // BFF API itself (which must stay reachable to perform login/logout).
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
