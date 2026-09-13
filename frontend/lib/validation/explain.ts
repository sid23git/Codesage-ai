import { z } from "zod";

/** Mirrors app/schemas/explain.py::ExplainRequest exactly, including its
 * `end_line >= start_line` cross-field check. */
export const explainSchema = z
  .object({
    file_path: z
      .string()
      .min(1, "Enter a file path.")
      .max(1024, "File path must be at most 1024 characters."),
    symbol: z
      .string()
      .max(255, "Symbol must be at most 255 characters.")
      .optional()
      .or(z.literal("")),
    start_line: z
      .string()
      .optional()
      .or(z.literal("")),
    end_line: z
      .string()
      .optional()
      .or(z.literal("")),
    question: z
      .string()
      .max(2000, "Question must be at most 2000 characters.")
      .optional()
      .or(z.literal("")),
  })
  .superRefine((values, ctx) => {
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

export type ExplainFormValues = z.infer<typeof explainSchema>;
