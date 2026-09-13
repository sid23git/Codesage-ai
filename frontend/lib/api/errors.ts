import { ApiError } from "@/lib/api/client";

/**
 * One place owning the friendly-message mapping for the shared M6 error
 * taxonomy (404/422/429/502/504), used identically by Ask, Explain, and
 * Review -- all three go through the backend's same `_raise_for_llm_error`
 * status mapping, so the frontend's presentation of it should match
 * across all three too.
 */
export function apiErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Please try again.";
  switch (error.status) {
    case 404:
      return "This repository or conversation could not be found.";
    case 422:
      return error.message || "That request couldn't be processed.";
    case 429:
      return "The AI provider is rate-limited right now. Please try again shortly.";
    case 502:
      return "The AI provider is temporarily unavailable. Please try again.";
    case 504:
      return "The request timed out. Please try again.";
    default:
      return error.message || "Something went wrong. Please try again.";
  }
}
