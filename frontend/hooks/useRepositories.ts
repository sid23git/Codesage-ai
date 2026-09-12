"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as repositoriesApi from "@/lib/api/repositories";
import { queryKeys } from "@/lib/query/keys";
import type { RepositoryCreate } from "@/lib/api/types";

export function useRepositories() {
  return useQuery({
    queryKey: queryKeys.repositories(),
    queryFn: () => repositoriesApi.listRepositories(),
  });
}

export function useRepository(id: number) {
  return useQuery({
    queryKey: queryKeys.repository(id),
    queryFn: () => repositoriesApi.getRepository(id),
    enabled: Number.isFinite(id),
  });
}

export function useCreateRepository() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RepositoryCreate) =>
      repositoriesApi.createRepository(payload),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.repositories() }),
  });
}

export function useIngestRepository(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => repositoriesApi.ingestRepository(id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.ingestion(id) }),
  });
}

export function useSyncRepository(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => repositoriesApi.syncRepository(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.repository(id) });
      queryClient.invalidateQueries({ queryKey: queryKeys.repositories() });
    },
  });
}

// In-flight ingestion statuses (app/schemas/ingestion.py::IngestionStatus) --
// polling continues only while the ingestion is in one of these states.
const IN_FLIGHT_STATUSES = new Set(["pending", "ingesting"]);
const POLL_BASE_MS = 2000;
const POLL_MAX_MS = 15000;

export function useLatestIngestion(
  id: number,
  options?: { pollWhilePending?: boolean },
) {
  return useQuery({
    queryKey: queryKeys.ingestion(id),
    queryFn: () => repositoriesApi.getLatestIngestion(id),
    enabled: Number.isFinite(id),
    retry: false,
    refetchInterval: (query) => {
      if (!options?.pollWhilePending) return false;
      const status = query.state.data?.status;
      // Stop as soon as a terminal state ("completed"/"failed") is
      // reached -- never poll forever. While in flight, back off
      // exponentially (2s, 4s, 8s, capped at 15s) rather than hammering
      // the backend at a fixed interval for a run that can take up to
      // INGESTION_TIMEOUT_SECONDS (60s server-side).
      if (!status || !IN_FLIGHT_STATUSES.has(status)) return false;
      const attempt = query.state.dataUpdateCount;
      return Math.min(POLL_BASE_MS * 2 ** attempt, POLL_MAX_MS);
    },
  });
}
