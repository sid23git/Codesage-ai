/**
 * Thin, generated-adjacent type aliases.
 *
 * `types.generated.ts` is produced by `npm run generate:types` (wrapping
 * `openapi-typescript` against the backend's own OpenAPI schema) and must
 * never be hand-edited. This file only gives the schemas convenient,
 * flat names -- it re-exports type IDENTITY, it does not redefine any
 * field, so it cannot itself drift from the backend's actual shapes.
 */

import type { components } from "./types.generated";

export type UserCreate = components["schemas"]["UserCreate"];
export type UserLogin = components["schemas"]["UserLogin"];
export type UserResponse = components["schemas"]["UserResponse"];
export type TokenResponse = components["schemas"]["TokenResponse"];

export type RepositoryCreate = components["schemas"]["RepositoryCreate"];
export type RepositoryUpdate = components["schemas"]["RepositoryUpdate"];
export type RepositoryResponse = components["schemas"]["RepositoryResponse"];
export type IngestionResponse = components["schemas"]["IngestionResponse"];
export type IngestionSummaryResponse =
  components["schemas"]["IngestionSummaryResponse"];

export type CodeSearchRequest = components["schemas"]["CodeSearchRequest"];
export type CodeSearchResponse = components["schemas"]["CodeSearchResponse"];
export type ChunkSearchResult = components["schemas"]["ChunkSearchResult"];

export type AskRequest = components["schemas"]["AskRequest"];
export type AskResponse = components["schemas"]["AskResponse"];
export type ExplainRequest = components["schemas"]["ExplainRequest"];
export type ExplainResponse = components["schemas"]["ExplainResponse"];
export type ReviewRequest = components["schemas"]["ReviewRequest"];
export type ReviewResponse = components["schemas"]["ReviewResponse"];
export type ReviewFindingResponse =
  components["schemas"]["ReviewFindingResponse"];
export type ReviewFocus = components["schemas"]["ReviewFocus"];

export type ConversationSummaryResponse =
  components["schemas"]["ConversationSummaryResponse"];
export type ConversationDetailResponse =
  components["schemas"]["ConversationDetailResponse"];
export type MessageResponse = components["schemas"]["MessageResponse"];
export type EvidenceCitation = components["schemas"]["EvidenceCitation"];

export type HTTPValidationError =
  components["schemas"]["HTTPValidationError"];
