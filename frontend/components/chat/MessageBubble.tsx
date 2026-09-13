import { EvidenceList } from "@/components/evidence/EvidenceList";
import { InsufficientEvidenceNotice } from "@/components/states/InsufficientEvidenceNotice";
import { MarkdownRenderer } from "@/components/markdown/MarkdownRenderer";
import type { ChatTurn } from "@/components/chat/types";

const INSUFFICIENT_EVIDENCE_TEXT =
  "I couldn't find enough relevant, sufficiently-confident evidence in this repository to answer that.";

/** Renders one turn -- user, assistant, or a failed assistant turn --
 * with a clear visual distinction between roles. */
export function MessageBubble({ turn }: { turn: ChatTurn }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground">
          {turn.content}
        </div>
      </div>
    );
  }

  if (turn.role === "assistant-error") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%] rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          {turn.message}
        </div>
      </div>
    );
  }

  // turn.role === "assistant"
  if (turn.status === "insufficient_evidence") {
    return (
      <div className="flex justify-start">
        <div className="max-w-[85%]">
          <InsufficientEvidenceNotice message={INSUFFICIENT_EVIDENCE_TEXT} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="flex max-w-[85%] flex-col gap-3 rounded-lg border border-border bg-card px-3 py-2">
        <MarkdownRenderer content={turn.content} />
        <EvidenceList evidence={turn.evidence} />
      </div>
    </div>
  );
}
