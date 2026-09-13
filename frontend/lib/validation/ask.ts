import { z } from "zod";

/** Mirrors app/schemas/conversation.py::AskRequest exactly. */
export const askMessageSchema = z.object({
  message: z
    .string()
    .min(1, "Enter a question.")
    .max(4000, "Questions must be at most 4000 characters."),
});

export type AskMessageFormValues = z.infer<typeof askMessageSchema>;
