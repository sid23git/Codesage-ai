"use client";

import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { useLogout, useMe } from "@/hooks/useAuth";

export function TopBar() {
  const router = useRouter();
  const { data: user } = useMe();
  const logout = useLogout();

  const onLogout = async () => {
    await logout.mutateAsync();
    router.replace("/login");
  };

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border px-6">
      <span className="text-sm text-muted-foreground">
        {user ? user.email : ""}
      </span>
      <Button variant="ghost" size="sm" onClick={onLogout} disabled={logout.isPending}>
        Sign out
      </Button>
    </header>
  );
}
