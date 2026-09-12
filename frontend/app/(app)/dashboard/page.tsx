"use client";

import Link from "next/link";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRepositories } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";

export default function DashboardPage() {
  const { data: repositories, isLoading, isError, error, refetch } =
    useRepositories();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">Repositories</h1>
        {repositories && repositories.length > 0 ? (
          <Button render={<Link href="/repositories/new" />} size="sm">
            Add repository
          </Button>
        ) : null}
      </div>

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
          action={
            <Button render={<Link href="/repositories/new" />}>
              Connect a repository
            </Button>
          }
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
                <CardContent className="flex flex-col gap-1">
                  <p className="truncate text-sm text-muted-foreground">
                    {repo.github_url}
                  </p>
                  <div className="mt-1 flex items-center justify-between text-xs text-muted-foreground">
                    <span>{repo.primary_language ?? "Language unknown"}</span>
                    <span>
                      Updated {new Date(repo.updated_at).toLocaleDateString()}
                    </span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  );
}
