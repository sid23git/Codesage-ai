"use client";

import { request } from "./client";
import type { UserCreate, UserLogin, UserResponse } from "./types";

/**
 * One module per backend router (mirrors `app/api/v1/auth.py` 1:1) --
 * when the backend adds an endpoint here, this is the one file that
 * grows a matching function.
 */

interface BffAuthResult {
  ok: boolean;
  autoLogin?: boolean;
}

export function login(credentials: UserLogin): Promise<BffAuthResult> {
  return request<BffAuthResult>("auth/login", {
    method: "POST",
    body: credentials,
  });
}

export function register(payload: UserCreate): Promise<BffAuthResult> {
  return request<BffAuthResult>("auth/register", {
    method: "POST",
    body: payload,
  });
}

export function logout(): Promise<BffAuthResult> {
  return request<BffAuthResult>("auth/logout", { method: "POST" });
}

export function me(): Promise<UserResponse> {
  return request<UserResponse>("auth/me");
}
