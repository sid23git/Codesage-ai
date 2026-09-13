import { toEvidenceViews } from "@/lib/api/evidence";
import type { EvidenceView } from "@/lib/api/evidence";
import type { MessageResponse } from "@/lib/api/types";

/**
 * Local chat-turn view model -- built up client-side as the conversation
 * progresses (from the initial hydration query, if resuming, plus each
 * new ask() mutation). Not a server resource in its own right, so it has
 * no query key of its own; see the M7 plan's state-management doctrine
 * (server data via TanStack Query, transient UI composition as local
 * state).
 */
export type ChatTurn =
  | { id: string; role: "user"; content: string; createdAt?: string }
  | {
      id: string;
      role: "assistant";
      status: "answered" | "insufficient_evidence";
      content: string;
      evidence: EvidenceView[];
      model?: string | null;
      createdAt?: string;
    }
  | { id: string; role: "assistant-error"; status: number | undefined; message: string };

/**
 * Maps a conversation's persisted `MessageResponse[]` into `ChatTurn[]`,
 * so both the Ask page's hydration path and the Conversation Detail page
 * render history through the exact same `MessageBubble` component --
 * one message-rendering system, not two.
 *
 * Persisted messages carry no explicit `insufficient_evidence` marker
 * (unlike a live `AskResponse`/`ExplainResponse`/`ReviewResponse`), so
 * every historical assistant message renders through the normal
 * "answered" path -- this is a backend schema characteristic (see
 * app/models/conversation.py::Message), not a frontend gap.
 */
export function hydratedTurnsFrom(messages: MessageResponse[]): ChatTurn[] {
  return messages.map((message) => {
    if (message.role === "user") {
      return {
        id: `hydrated-${message.id}`,
        role: "user",
        content: message.content,
        createdAt: message.created_at,
      };
    }
    return {
      id: `hydrated-${message.id}`,
      role: "assistant",
      status: "answered",
      content: message.content,
      evidence: toEvidenceViews(message.evidence ?? []),
      model: message.model,
      createdAt: message.created_at,
    };
  });
}
