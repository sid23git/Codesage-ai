"use client";

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import * as assistantApi from "@/lib/api/assistant";
import { queryKeys } from "@/lib/query/keys";
import type {
  AskRequest,
  AskResponse,
  ExplainRequest,
  ExplainResponse,
  ReviewRequest,
  ReviewResponse,
} from "@/lib/api/types";

/** Ask/Explain/Review all persist a turn whenever their response carries
 * a non-null `conversation_id` (Ask always does; Explain/Review only do
 * when one was supplied in the request) -- in that case, the
 * conversation-history list and that conversation's own detail query are
 * both now stale and should be invalidated. A `null` conversation_id
 * (Explain/Review's one-off, unpersisted case) touches no server state,
 * so nothing is invalidated. */
function invalidateConversationQueries(
  queryClient: QueryClient,
  repositoryId: number,
  conversationId: number | null | undefined,
) {
  if (!conversationId) return;
  queryClient.invalidateQueries({ queryKey: queryKeys.conversations(repositoryId) });
  queryClient.invalidateQueries({
    queryKey: queryKeys.conversation(repositoryId, conversationId),
  });
}

/** POST /repositories/{id}/ask */
export function useAsk(repositoryId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: AskRequest) => assistantApi.ask(repositoryId, payload),
    onSuccess: (response: AskResponse) =>
      invalidateConversationQueries(queryClient, repositoryId, response.conversation_id),
  });
}

/** POST /repositories/{id}/explain -- a one-shot analysis; the result
 * itself becomes local page state, not a cached query, but a supplied
 * conversation_id still means a turn was persisted server-side. */
export function useExplain(repositoryId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ExplainRequest) =>
      assistantApi.explain(repositoryId, payload),
    onSuccess: (response: ExplainResponse) =>
      invalidateConversationQueries(queryClient, repositoryId, response.conversation_id),
  });
}

/** POST /repositories/{id}/review -- same one-shot shape as useExplain. */
export function useReview(repositoryId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ReviewRequest) =>
      assistantApi.review(repositoryId, payload),
    onSuccess: (response: ReviewResponse) =>
      invalidateConversationQueries(queryClient, repositoryId, response.conversation_id),
  });
}

/** GET /repositories/{id}/conversations -- the conversation history list. */
export function useConversations(repositoryId: number) {
  return useQuery({
    queryKey: queryKeys.conversations(repositoryId),
    queryFn: () => assistantApi.listConversations(repositoryId),
    enabled: Number.isFinite(repositoryId),
  });
}

/** Hydrates an existing conversation's message history -- used both by
 * the Ask page (when loaded with a `?conversation=<id>` URL param) and
 * the Conversation Detail page. */
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
