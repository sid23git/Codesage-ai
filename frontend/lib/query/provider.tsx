"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { setUnauthorizedHandler } from "@/lib/api/client";

/**
 * Wraps the app in a single TanStack Query client (server state -- see
 * plan Section 9) and registers the global 401 handler once, so any
 * expired/invalid session redirects to /login regardless of which screen
 * triggered the request.
 */
export function QueryProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: (failureCount, error) => {
              const status = (error as { status?: number }).status;
              // Don't retry auth/validation/not-found errors -- only
              // transient upstream failures (429/502/504) are worth it.
              if (status && [401, 404, 422].includes(status)) return false;
              return failureCount < 2;
            },
            staleTime: 30_000,
          },
        },
      }),
  );

  useEffect(() => {
    setUnauthorizedHandler(() => {
      router.replace("/login?reason=expired");
    });
  }, [router]);

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}
