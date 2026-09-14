# syntax=docker/dockerfile:1
#
# Production image for the CodeSage frontend (Next.js, standalone output).
#
# Three stages: `deps` installs npm packages in their own cached layer,
# `builder` runs the actual production build, and `runner` is a clean slim
# image that only receives the standalone server Next.js produces (see
# next.config.ts's `output: "standalone"`) -- not node_modules, not the
# source tree, not any dev dependency.
#
# BACKEND_URL and the session-cookie settings are read at request time
# from the process environment (see docker-compose.yml) -- nothing here
# bakes in a backend URL or a secret. None of this app's env vars are
# NEXT_PUBLIC_-prefixed, so nothing needs to be supplied at build time
# either -- the same image works unmodified against any backend.

FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build


FROM node:20-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN groupadd --system nextjs && useradd --system --gid nextjs --home /app nextjs

# `output: "standalone"` produces a minimal server bundle that does NOT
# include public/ or .next/static on its own (Next.js requires copying
# both in manually) -- these three COPYs are the complete runtime surface.
COPY --from=builder /app/public ./public
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD ["node", "-e", "fetch('http://localhost:3000/login').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["node", "server.js"]
