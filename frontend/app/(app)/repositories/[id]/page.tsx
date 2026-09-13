"use client";

import { useParams } from "next/navigation";
import { useEffect, useRef } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { IngestionHistoryList } from "@/components/status/IngestionHistoryList";
import { IngestionPanel } from "@/components/status/IngestionPanel";
import { StatusBadge } from "@/components/status/StatusBadge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  useIngestionHistory,
  useIngestRepository,
  useLatestIngestion,
  useRepository,
  useSyncRepository,
} from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";

const TERMINAL_STATUSES = new Set(["completed", "failed"]);

export default function RepositoryOverviewPage() {
  const params = useParams<{ id: string }>();
  const repositoryId = Number(params.id);

  const repository = useRepository(repositoryId);
  const ingestion = useLatestIngestion(repositoryId, { pollWhilePending: true });
  const history = useIngestionHistory(repositoryId);
  const ingest = useIngestRepository(repositoryId);
  const sync = useSyncRepository(repositoryId);

  // The latest-ingestion query is polled in the background (not a
  // mutation), so there's no mutation onSuccess to hook into for "it just
  // finished." Watch for the transition into a terminal state here and
  // refresh the history list at that moment, per the Phase 2 requirement
  // to invalidate history when an ingestion completes/fails.
  const previousStatus = useRef<string | undefined>(undefined);
  useEffect(() => {
    const status = ingestion.data?.status;
    if (
      status &&
      TERMINAL_STATUSES.has(status) &&
      previousStatus.current !== status
    ) {
      history.refetch();
    }
    previousStatus.current = status;
  }, [ingestion.data?.status, history]);

  const onStartIngestion = async () => {
    try {
      await ingest.mutateAsync();
      toast.success("Ingestion started.");
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Failed to start ingestion.";
      toast.error(message);
    }
  };

  const onSync = async () => {
    try {
      await sync.mutateAsync();
      toast.success("Repository synced from GitHub.");
    } catch (error) {
      const message =
        error instanceof ApiError ? error.message : "Failed to sync repository.";
      toast.error(message);
    }
  };

  const onRefresh = () => {
    repository.refetch();
    ingestion.refetch();
    history.refetch();
  };

  if (repository.isLoading) {
    return <LoadingState rows={4} />;
  }

  if (repository.isError) {
    if (repository.error instanceof ApiError && repository.error.status === 404) {
      return (
        <EmptyState
          title="Repository not found"
          description="It may have been deleted, or it doesn't belong to your account."
        />
      );
    }
    return (
      <ErrorState
        status={repository.error instanceof ApiError ? repository.error.status : undefined}
        message={
          repository.error instanceof Error
            ? repository.error.message
            : "Failed to load repository."
        }
        onRetry={() => repository.refetch()}
      />
    );
  }

  const repo = repository.data;
  if (!repo) return null;

  // The ingestion query 404s (a normal, expected outcome) until the first
  // /ingest call ever succeeds -- IngestionPanel renders its own "not yet
  // ingested" state for that case, not an error.
  const ingestionNotYetStarted =
    ingestion.isError &&
    ingestion.error instanceof ApiError &&
    ingestion.error.status === 404;
  const ingestionHasOtherError = ingestion.isError && !ingestionNotYetStarted;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{repo.name}</h1>
          <a
            href={repo.github_url}
            target="_blank"
            rel="noreferrer noopener"
            className="text-sm text-muted-foreground underline"
          >
            {repo.github_url}
          </a>
        </div>
        <Button
          onClick={onRefresh}
          variant="ghost"
          size="sm"
          disabled={repository.isFetching || ingestion.isFetching || history.isFetching}
        >
          Refresh
        </Button>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center justify-between gap-2 text-base">
            Repository
            <StatusBadge status={repo.status} />
          </CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Primary language</dt>
            <dd>{repo.primary_language ?? "Unknown"}</dd>
            {repo.description ? (
              <>
                <dt className="text-muted-foreground">Description</dt>
                <dd>{repo.description}</dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">Added</dt>
            <dd>{new Date(repo.created_at).toLocaleString()}</dd>
            {repo.last_synced_at ? (
              <>
                <dt className="text-muted-foreground">Last synced</dt>
                <dd>{new Date(repo.last_synced_at).toLocaleString()}</dd>
              </>
            ) : null}
            {repo.stars !== null && repo.stars !== undefined ? (
              <>
                <dt className="text-muted-foreground">Stars</dt>
                <dd>{repo.stars.toLocaleString()}</dd>
              </>
            ) : null}
            {repo.forks !== null && repo.forks !== undefined ? (
              <>
                <dt className="text-muted-foreground">Forks</dt>
                <dd>{repo.forks.toLocaleString()}</dd>
              </>
            ) : null}
            {repo.default_branch ? (
              <>
                <dt className="text-muted-foreground">Default branch</dt>
                <dd>{repo.default_branch}</dd>
              </>
            ) : null}
          </dl>
          <Button
            onClick={onSync}
            disabled={sync.isPending}
            variant="outline"
            className="w-fit"
          >
            {sync.isPending ? "Syncing…" : "Sync from GitHub"}
          </Button>
        </CardContent>
      </Card>

      {ingestionHasOtherError ? (
        <ErrorState
          status={ingestion.error instanceof ApiError ? ingestion.error.status : undefined}
          message={
            ingestion.error instanceof Error
              ? ingestion.error.message
              : "Failed to load ingestion status."
          }
          onRetry={() => ingestion.refetch()}
        />
      ) : (
        <IngestionPanel
          ingestion={ingestionNotYetStarted ? undefined : ingestion.data}
          onStart={onStartIngestion}
          isStarting={ingest.isPending}
        />
      )}

      {history.data && history.data.length > 0 ? (
        <IngestionHistoryList runs={history.data} />
      ) : null}

      <Separator />

      <div>
        <h2 className="mb-2 text-sm font-medium text-muted-foreground">
          More on this repository
        </h2>
        <div className="flex gap-2">
          <Button variant="secondary" disabled title="Coming in a future phase">
            Ask
          </Button>
          <Button variant="secondary" disabled title="Coming in a future phase">
            Explain
          </Button>
          <Button variant="secondary" disabled title="Coming in a future phase">
            Review
          </Button>
        </div>
      </div>
    </div>
  );
}
