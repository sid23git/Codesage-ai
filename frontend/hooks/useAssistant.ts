"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import * as assistantApi from "@/lib/api/assistant";
import { queryKeys } from "@/lib/query/keys";
import type { AskRequest, ExplainRequest, ReviewRequest } from "@/lib/api/types";

/** POST /repositories/{id}/ask -- the one server-state write this page
 * performs. Query invalidation isn't relevant here: each answer becomes
 * local chat-turn state (components/chat/types.ts), not a cached list
 * that needs to stay in sync with a query. */
export function useAsk(repositoryId: number) {
  return useMutation({
    mutationFn: (payload: AskRequest) => assistantApi.ask(repositoryId, payload),
  });
}

/** POST /repositories/{id}/explain -- a one-shot analysis, not a cached
 * query; each submission's result simply replaces the previous one in
 * the page's local state. */
export function useExplain(repositoryId: number) {
  return useMutation({
    mutationFn: (payload: ExplainRequest) =>
      assistantApi.explain(repositoryId, payload),
  });
}

/** POST /repositories/{id}/review -- same one-shot shape as useExplain. */
export function useReview(repositoryId: number) {
  return useMutation({
    mutationFn: (payload: ReviewRequest) =>
      assistantApi.review(repositoryId, payload),
  });
}

/** Hydrates an existing conversation's message history when the page is
 * loaded with a `?conversation=<id>` URL param, so refreshing or sharing
 * the link doesn't lose the conversation -- without building the full
 * conversation-history list screen (a later phase). */
export function useConversation(
  repositoryId: number,
  conversationId: number | null,
) {
  return useQuery({
    queryKey: queryKeys.conversation(repositoryId, conversationId ?? -1),
    queryFn: () => assistantApi.getConversation(repositoryId, conversationId!),
    enabled: Number.isFinite(repositoryId) && conversationId !== null,
  });
}
