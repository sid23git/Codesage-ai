/**
 * `status: "insufficient_evidence"` is a normal 200 response, never an
 * error -- see the M7 plan, Section 9/10. This renders it as a calm,
 * intentional state, not a failure.
 */
export function InsufficientEvidenceNotice({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-border bg-muted/40 p-4 text-sm text-muted-foreground">
      <p className="font-medium text-foreground">Not enough evidence to answer</p>
      <p className="mt-1">{message}</p>
    </div>
  );
}
