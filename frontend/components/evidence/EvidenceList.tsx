import { EvidenceCitationCard } from "@/components/evidence/EvidenceCitation";
import type { EvidenceView } from "@/lib/api/evidence";

/** Always-visible list of an answer's cited sources -- never collapsed
 * behind a toggle; see the M7 plan's evidence-visibility priority. */
export function EvidenceList({ evidence }: { evidence: EvidenceView[] }) {
  if (evidence.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-medium text-muted-foreground">
        Sources ({evidence.length})
      </p>
      <div className="flex flex-col gap-2">
        {evidence.map((item) => (
          <EvidenceCitationCard key={item.chunkId} evidence={item} />
        ))}
      </div>
    </div>
  );
}
