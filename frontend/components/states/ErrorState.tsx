import { Button } from "@/components/ui/button";

/**
 * Distinguishes retry-able transient errors (429/502/504 -- upstream
 * GitHub/LLM failures per the verified backend behavior) from terminal
 * ones (404). 401s never reach this component -- they redirect instead
 * (see lib/query/provider.tsx).
 */
export function ErrorState({
  status,
  message,
  onRetry,
}: {
  status?: number;
  message: string;
  onRetry?: () => void;
}) {
  const isRetryable = status !== undefined && [429, 502, 504].includes(status);
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-8 text-center">
      <p className="text-sm font-medium text-foreground">
        {status === 404 ? "Not found" : "Something went wrong"}
      </p>
      <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
      {isRetryable && onRetry ? (
        <Button size="sm" variant="outline" onClick={onRetry}>
          Try again
        </Button>
      ) : null}
    </div>
  );
}
