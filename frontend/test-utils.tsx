import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";

/** A fresh, retry-free QueryClient per test so failures resolve immediately
 * instead of TanStack Query's default exponential-backoff retries. */
export function createTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
}

export function renderWithQueryClient(
  ui: ReactElement,
  client: QueryClient = createTestQueryClient(),
) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
    ),
  };
}

/**
 * Waits one real macrotask tick.
 *
 * `CodeBlock`'s highlighting effect resolves via a mocked `shiki.codeToHtml`
 * promise; in this test environment, `@testing-library`'s `findBy*`/
 * `waitFor` polling reliably misses that resolution when the test isn't
 * the first one to run in its file (a jsdom/Vitest timer-polling
 * interaction, not a product behavior) -- a real macrotask delay before
 * asserting is what actually works. Use this after `render()` and before
 * a plain (non-`find`) assertion whenever a test renders anything that
 * goes through `CodeBlock` (evidence citations, fenced Markdown code).
 */
export function flushMacrotask(ms = 50): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Builds a fetch Response-like object matching what `lib/api/client.ts`'s
 * `request()` expects (reads `.ok`, `.status`, `.text()`). */
export function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}
