"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingState } from "@/components/states/LoadingState";
import { useMe } from "@/hooks/useAuth";

export default function SettingsPage() {
  const { data: user, isLoading } = useMe();

  return (
    <div className="flex max-w-lg flex-col gap-6">
      <h1 className="text-xl font-semibold">Settings</h1>
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Account</CardTitle>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <LoadingState rows={2} />
          ) : (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">Email</dt>
              <dd>{user?.email}</dd>
              <dt className="text-muted-foreground">Member since</dt>
              <dd>
                {user ? new Date(user.created_at).toLocaleDateString() : "—"}
              </dd>
            </dl>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
