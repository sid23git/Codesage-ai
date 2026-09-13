import { MarkdownRenderer } from "@/components/markdown/MarkdownRenderer";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { EvidenceView } from "@/lib/api/evidence";
import type { ReviewFindingResponse } from "@/lib/api/types";

// Severity is always shown as its own visible text label (capitalized),
// never conveyed by color alone -- the Badge variant is just an accent.
const SEVERITY_VARIANT: Record<string, "destructive" | "secondary" | "outline"> = {
  critical: "destructive",
  high: "destructive",
  medium: "secondary",
  low: "outline",
};

export function FindingCard({
  finding,
  evidenceByChunkId,
}: {
  finding: ReviewFindingResponse;
  evidenceByChunkId: Map<number, EvidenceView>;
}) {
  const severityKey = finding.severity?.toLowerCase();
  const referencedEvidence = (finding.evidence_chunk_ids ?? [])
    .map((id) => evidenceByChunkId.get(id))
    .filter((item): item is EvidenceView => Boolean(item));

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2 text-base">
          <span>{finding.title}</span>
          {finding.severity ? (
            <Badge variant={SEVERITY_VARIANT[severityKey ?? ""] ?? "outline"}>
              {finding.severity}
            </Badge>
          ) : null}
          {finding.category ? <Badge variant="outline">{finding.category}</Badge> : null}
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {finding.file_path ? (
          <p className="font-mono text-xs text-muted-foreground">
            {finding.file_path}
            {finding.start_line
              ? `:${finding.start_line}${
                  finding.end_line && finding.end_line !== finding.start_line
                    ? `-${finding.end_line}`
                    : ""
                }`
              : ""}
          </p>
        ) : null}

        {finding.explanation ? <MarkdownRenderer content={finding.explanation} /> : null}

        {finding.recommendation ? (
          <div>
            <p className="text-xs font-medium text-muted-foreground">Recommendation</p>
            <MarkdownRenderer content={finding.recommendation} />
          </div>
        ) : null}

        {referencedEvidence.length > 0 ? (
          <p className="text-xs text-muted-foreground">
            Supported by:{" "}
            {referencedEvidence
              .map((item) => `${item.filePath}:${item.startLine}-${item.endLine}`)
              .join(", ")}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
