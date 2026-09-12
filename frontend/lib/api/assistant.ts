"use client";

import { request } from "./client";
import type {
  AskRequest,
  AskResponse,
  ConversationDetailResponse,
  ConversationSummaryResponse,
  ExplainRequest,
  ExplainResponse,
  ReviewRequest,
  ReviewResponse,
} from "./types";

/** Mirrors `app/api/v1/assistant.py` 1:1. */

export function ask(
  repositoryId: number,
  payload: AskRequest,
): Promise<AskResponse> {
  return request<AskResponse>(`repositories/${repositoryId}/ask`, {
    method: "POST",
    body: payload,
  });
}

export function explain(
  repositoryId: number,
  payload: ExplainRequest,
): Promise<ExplainResponse> {
  return request<ExplainResponse>(`repositories/${repositoryId}/explain`, {
    method: "POST",
    body: payload,
  });
}

export function review(
  repositoryId: number,
  payload: ReviewRequest,
): Promise<ReviewResponse> {
  return request<ReviewResponse>(`repositories/${repositoryId}/review`, {
    method: "POST",
    body: payload,
  });
}

export function listConversations(
  repositoryId: number,
): Promise<ConversationSummaryResponse[]> {
  return request<ConversationSummaryResponse[]>(
    `repositories/${repositoryId}/conversations`,
  );
}

export function getConversation(
  repositoryId: number,
  conversationId: number,
): Promise<ConversationDetailResponse> {
  return request<ConversationDetailResponse>(
    `repositories/${repositoryId}/conversations/${conversationId}`,
  );
}
