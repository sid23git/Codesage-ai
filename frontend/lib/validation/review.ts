import { z } from "zod";

/** Mirrors app/schemas/review.py::ReviewRequest exactly: at least one of
 * file_path/user_code, the 20,000-character user_code cap, and the
 * end_line >= start_line cross-field check. */
export const MAX_USER_CODE_CHARS = 20000;

export const reviewFocusValues = [
  "general",
  "bugs",
  "security",
  "maintainability",
  "performance",
  "style",
] as const;

export const reviewSchema = z
  .object({
    file_path: z
      .string()
      .max(1024, "File path must be at most 1024 characters.")
      .optional()
      .or(z.literal("")),
    symbol: z
      .string()
      .max(255, "Symbol must be at most 255 characters.")
      .optional()
      .or(z.literal("")),
    start_line: z.string().optional().or(z.literal("")),
    end_line: z.string().optional().or(z.literal("")),
    focus: z.enum(reviewFocusValues),
    user_code: z
      .string()
      .max(
        MAX_USER_CODE_CHARS,
        `Code must be at most ${MAX_USER_CODE_CHARS.toLocaleString()} characters.`,
      )
      .optional()
      .or(z.literal("")),
  })
  .superRefine((values, ctx) => {
    if (!values.file_path && !values.user_code) {
      ctx.addIssue({
        code: "custom",
        path: ["file_path"],
        message: "Provide a file path or paste code to review.",
      });
    }
    const start = values.start_line ? Number(values.start_line) : undefined;
    const end = values.end_line ? Number(values.end_line) : undefined;
    if (values.start_line && (!Number.isInteger(start) || (start ?? 0) < 1)) {
      ctx.addIssue({
        code: "custom",
        path: ["start_line"],
        message: "Start line must be a positive whole number.",
      });
    }
    if (values.end_line && (!Number.isInteger(end) || (end ?? 0) < 1)) {
      ctx.addIssue({
        code: "custom",
        path: ["end_line"],
        message: "End line must be a positive whole number.",
      });
    }
    if (start !== undefined && end !== undefined && end < start) {
      ctx.addIssue({
        code: "custom",
        path: ["end_line"],
        message: "End line must be greater than or equal to start line.",
      });
    }
  });

export type ReviewFormValues = z.infer<typeof reviewSchema>;
