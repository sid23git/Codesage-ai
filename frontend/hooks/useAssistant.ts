"use client";

import { useMutation, useQuery } from "@tanstack/react-query";

import * as assistantApi from "@/lib/api/assistant";
import { queryKeys } from "@/lib/query/keys";
import type { AskRequest } from "@/lib/api/types";

/** POST /repositories/{id}/ask -- the one server-state write this page
 * performs. Query invalidation isn't relevant here: each answer becomes
 * local chat-turn state (components/chat/types.ts), not a cached list
 * that needs to stay in sync with a query. */
export function useAsk(repositoryId: number) {
  return useMutation({
    mutationFn: (payload: AskRequest) => assistantApi.ask(repositoryId, payload),
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
