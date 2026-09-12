/**
 * Query key factories -- one source of truth per resource so cache
 * invalidation (e.g. after triggering an ingestion) can target exactly
 * the right keys without magic strings scattered across hooks.
 */
export const queryKeys = {
  me: () => ["me"] as const,
  repositories: () => ["repositories"] as const,
  repository: (id: number) => ["repositories", id] as const,
  ingestion: (id: number) => ["repositories", id, "ingestion"] as const,
  ingestions: (id: number) => ["repositories", id, "ingestions"] as const,
  conversations: (repositoryId: number) =>
    ["repositories", repositoryId, "conversations"] as const,
  conversation: (repositoryId: number, conversationId: number) =>
    ["repositories", repositoryId, "conversations", conversationId] as const,
};
