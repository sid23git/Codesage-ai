"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/status/StatusBadge";
import type { IngestionSummaryResponse } from "@/lib/api/types";

// The backend returns every historical run with no pagination
// (IngestionService.list_ingestions, ordered created_at DESC) -- capping
// how many we render is a display decision, not an invented endpoint.
const MAX_VISIBLE_RUNS = 5;

export function IngestionHistoryList({
  runs,
}: {
  runs: IngestionSummaryResponse[];
}) {
  if (runs.length === 0) {
    return null;
  }

  const visible = runs.slice(0, MAX_VISIBLE_RUNS);
  const hiddenCount = runs.length - visible.length;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Ingestion history</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <ul className="flex flex-col divide-y divide-border">
          {visible.map((run) => (
            <li
              key={run.id}
              className="flex items-center justify-between gap-3 py-2 text-sm"
            >
              <div className="flex items-center gap-2">
                <StatusBadge status={run.status} />
                <span className="text-muted-foreground">
                  {new Date(run.created_at).toLocaleString()}
                </span>
              </div>
              <span className="text-muted-foreground">
                {run.status === "failed"
                  ? (run.error_message ?? "Failed")
                  : `${run.file_count.toLocaleString()} files, ${run.total_lines.toLocaleString()} lines`}
              </span>
            </li>
          ))}
        </ul>
        {hiddenCount > 0 ? (
          <p className="text-xs text-muted-foreground">
            {hiddenCount} earlier {hiddenCount === 1 ? "run" : "runs"} not shown.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
