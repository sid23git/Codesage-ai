"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { RepoToolNav } from "@/components/layout/RepoToolNav";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useConversations } from "@/hooks/useAssistant";
import { useRepository } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";

export default function ConversationsPage() {
  const params = useParams<{ id: string }>();
  const repositoryId = Number(params.id);

  const repository = useRepository(repositoryId);
  const conversations = useConversations(repositoryId);

  // A malformed URL (e.g. /repositories/abc/conversations) disables
  // every query below rather than erroring, so without this guard the
  // page would fall through every check and render nothing -- a
  // permanent blank screen instead of a clear "not found."
  if (!Number.isFinite(repositoryId)) {
    return (
      <EmptyState
        title="Repository not found"
        description="It may have been deleted, or it doesn't belong to your account."
      />
    );
  }

  if (repository.isLoading) {
    return <LoadingState rows={4} />;
  }

  if (repository.isError) {
    return (
      <ErrorState
        status={repository.error instanceof ApiError ? repository.error.status : undefined}
        message={
          repository.error instanceof Error
            ? repository.error.message
            : "Failed to load repository."
        }
        onRetry={() => repository.refetch()}
      />
    );
  }

  const repo = repository.data;
  if (!repo) return null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <RepoToolNav repositoryId={repositoryId} repoName={repo.name} active="conversations" />
        <h1 className="mt-2 text-xl font-semibold">Conversation history</h1>
      </div>

      {conversations.isLoading ? <LoadingState rows={3} /> : null}

      {conversations.isError ? (
        <ErrorState
          status={
            conversations.error instanceof ApiError ? conversations.error.status : undefined
          }
          message={
            conversations.error instanceof Error
              ? conversations.error.message
              : "Failed to load conversations."
          }
          onRetry={() => conversations.refetch()}
        />
      ) : null}

      {conversations.data && conversations.data.length === 0 ? (
        <EmptyState
          title="No conversations yet"
          description={`Ask a question about ${repo.name} to start your first conversation.`}
          action={
            <Button render={<Link href={`/repositories/${repositoryId}/ask`} />}>
              Ask a question
            </Button>
          }
        />
      ) : null}

      {conversations.data && conversations.data.length > 0 ? (
        <div className="flex flex-col gap-2">
          {conversations.data.map((conversation) => (
            <Link
              key={conversation.id}
              href={`/repositories/${repositoryId}/conversations/${conversation.id}`}
            >
              <Card className="transition-colors hover:border-foreground/30">
                <CardHeader>
                  <CardTitle className="text-base">
                    {conversation.title ?? `Conversation #${conversation.id}`}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">
                    Updated {new Date(conversation.updated_at).toLocaleString()}
                  </p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      ) : null}
    </div>
  );
}
