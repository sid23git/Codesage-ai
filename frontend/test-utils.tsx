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

/** Builds a fetch Response-like object matching what `lib/api/client.ts`'s
 * `request()` expects (reads `.ok`, `.status`, `.text()`). */
export function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}
