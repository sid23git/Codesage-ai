import { z } from "zod";

/**
 * Mirrors app/schemas/repository.py::RepositoryCreate. The backend's
 * `validate_github_url` (app/github/url_parser.py::parse_github_url) is
 * the actual SSRF-protection boundary (HTTPS + host must be exactly
 * github.com + exactly owner/repo path segments); this regex only gives
 * the user instant client-side feedback for the common cases -- the
 * backend remains authoritative and is never bypassed.
 */
const GITHUB_URL_PATTERN =
  /^https:\/\/github\.com\/[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\/[A-Za-z0-9._-]+(?:\.git)?\/?$/;

export const repositoryCreateSchema = z.object({
  name: z
    .string()
    .min(1, "Name is required.")
    .max(255, "Name must be at most 255 characters."),
  github_url: z
    .string()
    .min(1, "GitHub URL is required.")
    .max(1024, "GitHub URL must be at most 1024 characters.")
    .regex(
      GITHUB_URL_PATTERN,
      "Must be a GitHub repository URL, e.g. https://github.com/owner/repo",
    ),
  description: z
    .string()
    .max(5000, "Description must be at most 5000 characters.")
    .optional()
    .or(z.literal("")),
  primary_language: z
    .string()
    .max(100, "Primary language must be at most 100 characters.")
    .optional()
    .or(z.literal("")),
});

export type RepositoryCreateFormValues = z.infer<typeof repositoryCreateSchema>;
