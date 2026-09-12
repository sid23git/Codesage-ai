"use client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status/StatusBadge";
import type { IngestionResponse } from "@/lib/api/types";

/**
 * Renders the latest ingestion's state and the one action that makes sense
 * for it. The backend returns no progress-percentage field (see
 * app/schemas/ingestion.py::IngestionResponse) -- this deliberately shows
 * status/counts/timestamps only, never a fabricated progress bar.
 */
export function IngestionPanel({
  ingestion,
  onStart,
  isStarting,
}: {
  ingestion: IngestionResponse | undefined;
  onStart: () => void;
  isStarting: boolean;
}) {
  if (!ingestion) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Ingestion</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <p className="text-sm text-muted-foreground">
            This repository hasn&apos;t been ingested yet. Ingestion downloads
            the repository source, scans and analyzes it, and is required
            before you can ask questions about it.
          </p>
          <Button onClick={onStart} disabled={isStarting} className="w-fit">
            {isStarting ? "Starting…" : "Start ingestion"}
          </Button>
        </CardContent>
      </Card>
    );
  }

  const isInFlight = ingestion.status === "pending" || ingestion.status === "ingesting";
  const isFailed = ingestion.status === "failed";
  const isCompleted = ingestion.status === "completed";

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2 text-base">
          Ingestion
          <StatusBadge status={ingestion.status} />
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {isInFlight ? (
          <p className="text-sm text-muted-foreground">
            Downloading and analyzing the repository&apos;s source. This can
            take up to a minute for larger repositories.
          </p>
        ) : null}

        {isFailed ? (
          <p className="text-sm text-destructive">
            {ingestion.error_message ?? "Ingestion failed for an unknown reason."}
          </p>
        ) : null}

        {isCompleted ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
            <dt className="text-muted-foreground">Files</dt>
            <dd>{ingestion.file_count.toLocaleString()}</dd>
            <dt className="text-muted-foreground">Lines</dt>
            <dd>{ingestion.total_lines.toLocaleString()}</dd>
            {ingestion.primary_language ? (
              <>
                <dt className="text-muted-foreground">Primary language</dt>
                <dd>{ingestion.primary_language}</dd>
              </>
            ) : null}
            {ingestion.completed_at ? (
              <>
                <dt className="text-muted-foreground">Completed</dt>
                <dd>{new Date(ingestion.completed_at).toLocaleString()}</dd>
              </>
            ) : null}
          </dl>
        ) : null}

        {isFailed ? (
          <Button onClick={onStart} disabled={isStarting} variant="outline" className="w-fit">
            {isStarting ? "Retrying…" : "Retry ingestion"}
          </Button>
        ) : null}

        {isCompleted ? (
          <Button onClick={onStart} disabled={isStarting} variant="outline" className="w-fit">
            {isStarting ? "Starting…" : "Re-ingest"}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
