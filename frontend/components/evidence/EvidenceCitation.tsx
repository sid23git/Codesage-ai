import { CodeBlock } from "@/components/code/CodeBlock";
import { Badge } from "@/components/ui/badge";
import type { EvidenceView } from "@/lib/api/evidence";

/**
 * One retrieved/cited source, visible by default (never hidden behind a
 * click) -- CodeSage's grounding claims are only useful if the reader can
 * immediately see the code they refer to.
 */
export function EvidenceCitationCard({ evidence }: { evidence: EvidenceView }) {
  const location = `${evidence.filePath}:${evidence.startLine}-${evidence.endLine}`;

  return (
    <div className="overflow-hidden rounded-md border border-border">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/40 px-3 py-1.5 text-xs">
        <span className="font-mono font-medium text-foreground">{location}</span>
        {evidence.name ? <Badge variant="outline">{evidence.name}</Badge> : null}
        {evidence.language ? (
          <span className="text-muted-foreground">{evidence.language}</span>
        ) : null}
        {evidence.retrievalSources?.length ? (
          <span className="text-muted-foreground">
            via {evidence.retrievalSources.join(" + ")}
          </span>
        ) : null}
        <span className="ml-auto text-muted-foreground">
          relevance {evidence.score.toFixed(2)}
        </span>
      </div>
      <CodeBlock
        code={evidence.text}
        language={evidence.language}
        startLine={evidence.startLine}
      />
    </div>
  );
}
