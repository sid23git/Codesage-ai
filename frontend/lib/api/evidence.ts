import type { ChunkSearchResult, EvidenceCitation } from "./types";

/**
 * Normalizes the two backend evidence shapes into one view model so a
 * single `EvidenceCitation`/`EvidenceList` component can render both --
 * see the M7 plan, Section 11.
 *
 * - `ChunkSearchResult`: live evidence from /search, /ask, /explain, /review
 *   (full `chunk_text`).
 * - `EvidenceCitation`: persisted evidence on a stored conversation
 *   `Message` (bounded `snippet`, truncated server-side to 500 chars).
 */
export interface EvidenceView {
  chunkId: number;
  filePath: string;
  startLine: number;
  endLine: number;
  language: string | null;
  name: string | null;
  score: number;
  text: string;
  /** Only present for live `ChunkSearchResult` evidence (e.g. /ask) --
   * persisted `EvidenceCitation` rows don't carry this, so it's undefined
   * when rendering citations loaded from a stored conversation. */
  retrievalSources?: string[];
}

export function toEvidenceView(
  input: ChunkSearchResult | EvidenceCitation,
): EvidenceView {
  const text = "chunk_text" in input ? input.chunk_text : input.snippet;
  return {
    chunkId: input.chunk_id,
    filePath: input.file_path,
    startLine: input.start_line,
    endLine: input.end_line,
    language: input.language ?? null,
    name: input.name ?? null,
    score: input.score,
    text,
    retrievalSources: "retrieval_sources" in input ? input.retrieval_sources : undefined,
  };
}

export function toEvidenceViews(
  inputs: (ChunkSearchResult | EvidenceCitation)[],
): EvidenceView[] {
  return inputs.map(toEvidenceView);
}
