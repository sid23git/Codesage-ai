"use client";

/**
 * Low-level, browser-side request helper. Every call goes to same-origin
 * `/api/bff/*` -- never directly to FastAPI -- so this file has no notion
 * of a backend base URL at all (that lives only in `lib/server/*`).
 *
 * Centralizes: auth-header injection (none needed here -- the httpOnly
 * cookie is sent automatically by the browser), typed error unwrapping,
 * and the global 401 -> redirect-to-login behavior, so individual screens
 * never re-implement any of this.
 */

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function extractMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const errorField = (body as { error?: unknown }).error;
    if (errorField && typeof errorField === "object") {
      const detail = (errorField as { detail?: unknown; message?: unknown })
        .detail ?? (errorField as { message?: unknown }).message;
      if (typeof detail === "string") return detail;
    }
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

let onUnauthorized: (() => void) | null = null;

/** Registered once, near the query client, so every request shares one 401 handler. */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

export async function request<T>(
  path: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const { method = "GET", body } = init;

  const response = await fetch(`/api/bff/${path}`.replace(/\/{2,}/g, "/"), {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : {},
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  const text = await response.text();
  const parsed: unknown = text ? JSON.parse(text) : null;

  if (!response.ok) {
    if (response.status === 401) {
      onUnauthorized?.();
    }
    throw new ApiError(
      response.status,
      extractMessage(parsed, `Request failed with status ${response.status}`),
    );
  }

  return parsed as T;
}
