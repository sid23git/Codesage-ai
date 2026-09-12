"use client";

import { request } from "./client";
import type {
  CodeSearchRequest,
  CodeSearchResponse,
  IngestionResponse,
  IngestionSummaryResponse,
  RepositoryCreate,
  RepositoryResponse,
  RepositoryUpdate,
} from "./types";

/** Mirrors `app/api/v1/repositories.py` 1:1. */

export function listRepositories(): Promise<RepositoryResponse[]> {
  return request<RepositoryResponse[]>("repositories");
}

export function createRepository(
  payload: RepositoryCreate,
): Promise<RepositoryResponse> {
  return request<RepositoryResponse>("repositories", {
    method: "POST",
    body: payload,
  });
}

export function getRepository(id: number): Promise<RepositoryResponse> {
  return request<RepositoryResponse>(`repositories/${id}`);
}

export function updateRepository(
  id: number,
  payload: RepositoryUpdate,
): Promise<RepositoryResponse> {
  return request<RepositoryResponse>(`repositories/${id}`, {
    method: "PUT",
    body: payload,
  });
}

export function deleteRepository(id: number): Promise<null> {
  return request<null>(`repositories/${id}`, { method: "DELETE" });
}

export function syncRepository(id: number): Promise<RepositoryResponse> {
  return request<RepositoryResponse>(`repositories/${id}/sync`, {
    method: "POST",
  });
}

export function ingestRepository(id: number): Promise<IngestionResponse> {
  return request<IngestionResponse>(`repositories/${id}/ingest`, {
    method: "POST",
  });
}

export function getLatestIngestion(id: number): Promise<IngestionResponse> {
  return request<IngestionResponse>(`repositories/${id}/ingestion`);
}

export function listIngestions(
  id: number,
): Promise<IngestionSummaryResponse[]> {
  return request<IngestionSummaryResponse[]>(`repositories/${id}/ingestions`);
}

export function getIngestion(
  id: number,
  ingestionId: number,
): Promise<IngestionResponse> {
  return request<IngestionResponse>(
    `repositories/${id}/ingestions/${ingestionId}`,
  );
}

export function searchRepository(
  id: number,
  payload: CodeSearchRequest,
): Promise<CodeSearchResponse> {
  return request<CodeSearchResponse>(`repositories/${id}/search`, {
    method: "POST",
    body: payload,
  });
}
