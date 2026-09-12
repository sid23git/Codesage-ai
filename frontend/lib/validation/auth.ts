import { z } from "zod";

/**
 * Mirrors the backend's own Pydantic constraints (app/schemas/user.py,
 * app/schemas/auth.py) so a client-side rejection matches what the API
 * would reject with a 422 for -- the user sees the same validation
 * instantly, without a round trip.
 */

export const loginSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(1, "Password is required."),
});
export type LoginFormValues = z.infer<typeof loginSchema>;

export const registerSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z
    .string()
    .min(8, "Password must be at least 8 characters.")
    .max(128, "Password must be at most 128 characters."),
});
export type RegisterFormValues = z.infer<typeof registerSchema>;
