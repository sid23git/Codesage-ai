import type { EvidenceView } from "@/lib/api/evidence";

/**
 * Local chat-turn view model -- built up client-side as the conversation
 * progresses (from the initial hydration query, if resuming, plus each
 * new ask() mutation). Not a server resource in its own right, so it has
 * no query key of its own; see the M7 plan's state-management doctrine
 * (server data via TanStack Query, transient UI composition as local
 * state).
 */
export type ChatTurn =
  | { id: string; role: "user"; content: string }
  | {
      id: string;
      role: "assistant";
      status: "answered" | "insufficient_evidence";
      content: string;
      evidence: EvidenceView[];
      model?: string | null;
    }
  | { id: string; role: "assistant-error"; status: number | undefined; message: string };
