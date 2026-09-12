import { QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Testing-library's `waitFor` polls using `setTimeout`, which is faked
// while `vi.useFakeTimers()` is active and never advances on its own --
// `advanceTimersByTimeAsync` both advances fake timers AND flushes pending
// microtasks (Promise resolutions), so it's used here in place of
// `waitFor` for anything under the fake-timers describe block below.
// Wrapped in `act()` since it triggers React state updates (the resolved
// fetch's data landing in the query cache) outside of an event handler.
async function flush(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

/** Advances the fake clock in small steps, up to `maxMs`, stopping as soon
 * as `predicate()` is true. Small steps (rather than one large jump) avoid
 * timer-scheduling edge cases where a fetch fires exactly at the boundary
 * of a single big `advanceTimersByTimeAsync` call and its resolution isn't
 * yet reflected in React state by the time that call returns. */
async function advanceUntil(
  predicate: () => boolean,
  { stepMs = 250, maxMs = 20_000 } = {},
) {
  let elapsed = 0;
  while (!predicate() && elapsed < maxMs) {
    await flush(stepMs);
    elapsed += stepMs;
  }
}

import { useIngestRepository, useLatestIngestion } from "@/hooks/useRepositories";
import { createTestQueryClient, jsonResponse } from "@/test-utils";

function makeWrapper() {
  const client = createTestQueryClient();
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return Wrapper;
}

function ingestionResponse(status: string, extra: Record<string, unknown> = {}) {
  return {
    id: 1,
    repository_id: 1,
    status,
    commit_sha: "abc123",
    file_count: 0,
    total_size_bytes: 0,
    total_lines: 0,
    primary_language: null,
    language_stats: null,
    directory_summary: null,
    file_catalog: null,
    error_message: null,
    started_at: "2026-01-01T00:00:00Z",
    completed_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...extra,
  };
}

describe("useLatestIngestion polling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("polls with exponential backoff while in flight and stops at a completed terminal state", async () => {
    const fetchMock = fetch as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, ingestionResponse("ingesting")))
      .mockResolvedValueOnce(jsonResponse(200, ingestionResponse("ingesting")))
      .mockResolvedValueOnce(
        jsonResponse(
          200,
          ingestionResponse("completed", { file_count: 42, total_lines: 1000 }),
        ),
      );

    const { result } = renderHook(
      () => useLatestIngestion(1, { pollWhilePending: true }),
      { wrapper: makeWrapper() },
    );

    await flush();
    expect(result.current.data?.status).toBe("ingesting");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // First backoff interval: 2000 * 2^1 = 4000ms.
    await advanceUntil(() => fetchMock.mock.calls.length >= 2);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    // Second backoff interval: 2000 * 2^2 = 8000ms.
    await advanceUntil(() => result.current.data?.status === "completed");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result.current.data?.file_count).toBe(42);

    // Terminal state reached -- no further polling even after a long wait.
    await flush(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("stops polling immediately at a failed terminal state and surfaces error_message", async () => {
    const fetchMock = fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(
      jsonResponse(
        200,
        ingestionResponse("failed", { error_message: "Archive too large" }),
      ),
    );

    const { result } = renderHook(
      () => useLatestIngestion(1, { pollWhilePending: true }),
      { wrapper: makeWrapper() },
    );

    await flush();
    expect(result.current.data?.status).toBe("failed");
    expect(result.current.data?.error_message).toBe("Archive too large");

    await flush(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("does not poll at all when pollWhilePending is not requested", async () => {
    const fetchMock = fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse(200, ingestionResponse("ingesting")));

    renderHook(() => useLatestIngestion(1), { wrapper: makeWrapper() });

    await flush();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await flush(60_000);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("useIngestRepository (retry/restart action)", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("triggers a fresh ingestion via POST /repositories/{id}/ingest", async () => {
    const fetchMock = fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValue(jsonResponse(200, ingestionResponse("ingesting")));

    const { result } = renderHook(() => useIngestRepository(1), {
      wrapper: makeWrapper(),
    });

    await result.current.mutateAsync();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/bff/repositories/1/ingest",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
