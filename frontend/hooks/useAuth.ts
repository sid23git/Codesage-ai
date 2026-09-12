"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import * as authApi from "@/lib/api/auth";
import { queryKeys } from "@/lib/query/keys";
import type { UserCreate, UserLogin } from "@/lib/api/types";

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (credentials: UserLogin) => authApi.login(credentials),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.me() }),
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: UserCreate) => authApi.register(payload),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.me() }),
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => authApi.logout(),
    onSuccess: () => queryClient.clear(),
  });
}

export function useMe(enabled = true) {
  return useQuery({
    queryKey: queryKeys.me(),
    queryFn: () => authApi.me(),
    enabled,
    retry: false,
  });
}
