import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a minimal `.next/standalone` build (the app plus only the
  // node_modules it actually traced as used) -- the shape a Docker image
  // wants; `next dev`/`next start` are unaffected either way.
  output: "standalone",

  async headers() {
    return [
      {
        // Applies to every route this app serves, including /api/bff/*.
        source: "/:path*",
        headers: [
          // Never let this app be framed by another origin (clickjacking).
          { key: "X-Frame-Options", value: "DENY" },
          // Stop the browser from MIME-sniffing a response into executing
          // as something other than its declared Content-Type.
          { key: "X-Content-Type-Options", value: "nosniff" },
          // Don't leak the full referring URL (which can carry
          // repository/conversation IDs in the path) to third-party
          // destinations -- only the origin, and only cross-origin.
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          // Disable a handful of browser features this app never uses.
          // Deliberately not a full Permissions-Policy audit -- just the
          // obvious, safe-to-disable defaults.
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          // Force HTTPS for a year, including subdomains, once a browser
          // has seen this header once. Harmless over plain HTTP in local
          // dev -- browsers only honor HSTS on an actual HTTPS response.
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
