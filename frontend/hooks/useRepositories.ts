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

export function useLatestIngestion(id: number, options?: { pollWhilePending?: boolean }) {
  return useQuery({
    queryKey: queryKeys.ingestion(id),
    queryFn: () => repositoriesApi.getLatestIngestion(id),
    enabled: Number.isFinite(id),
    retry: false,
    refetchInterval: (query) => {
      if (!options?.pollWhilePending) return false;
      const status = query.state.data?.status;
      // Only poll while an ingestion is actually in flight ("pending" or
      // "ingesting" -- app/schemas/ingestion.py::IngestionStatus) -- stop
      // as soon as it reaches a terminal state ("completed"/"failed"), per
      // the plan's performance notes on avoiding naive fixed-interval
      // polling.
      return status === "pending" || status === "ingesting" ? 3000 : false;
    },
  });
}
