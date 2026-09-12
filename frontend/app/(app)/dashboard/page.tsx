"use client";

import Link from "next/link";

import { StatusBadge } from "@/components/status/StatusBadge";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRepositories } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";

/**
 * Phase 0 smoke-test dashboard: proves a logged-in session can reach the
 * backend through the BFF end to end. The full connect-repository flow,
 * ingestion status UI, etc. are built out in Phase 1.
 */
export default function DashboardPage() {
  const { data: repositories, isLoading, isError, error, refetch } =
    useRepositories();

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Repositories</h1>

      {isLoading ? <LoadingState rows={3} /> : null}

      {isError ? (
        <ErrorState
          status={error instanceof ApiError ? error.status : undefined}
          message={error instanceof Error ? error.message : "Failed to load repositories."}
          onRetry={() => refetch()}
        />
      ) : null}

      {repositories && repositories.length === 0 ? (
        <EmptyState
          title="No repositories yet"
          description="Connect your first GitHub repository to start asking questions about it."
        />
      ) : null}

      {repositories && repositories.length > 0 ? (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {repositories.map((repo) => (
            <Link key={repo.id} href={`/repositories/${repo.id}`}>
              <Card className="h-full transition-colors hover:border-foreground/30">
                <CardHeader>
                  <CardTitle className="flex items-center justify-between gap-2 text-base">
                    <span className="truncate">{repo.name}</span>
                    <StatusBadge status={repo.status} />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="truncate text-sm text-muted-foreground">
                    {repo.full_name}
                  </p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  );
}
