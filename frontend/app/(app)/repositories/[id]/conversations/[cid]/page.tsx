"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { MessageBubble } from "@/components/chat/MessageBubble";
import { hydratedTurnsFrom } from "@/components/chat/types";
import { RepoToolNav } from "@/components/layout/RepoToolNav";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { Button } from "@/components/ui/button";
import { useConversation } from "@/hooks/useAssistant";
import { useRepository } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";

export default function ConversationDetailPage() {
  const params = useParams<{ id: string; cid: string }>();
  const repositoryId = Number(params.id);
  const rawConversationId = Number(params.cid);
  // Guard against a malformed URL (e.g. /conversations/abc) before ever
  // calling the API with it -- `useConversation`'s query stays disabled
  // (matching its own "no conversation" behavior) rather than issuing a
  // request built from NaN.
  const conversationId = Number.isFinite(rawConversationId) ? rawConversationId : null;

  const repository = useRepository(repositoryId);
  const conversation = useConversation(repositoryId, conversationId);

  // A malformed URL (e.g. /repositories/abc/conversations/5) disables
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

  if (repository.isLoading || (conversation.isLoading && conversationId !== null)) {
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

  if (conversationId === null || conversation.isError) {
    if (
      conversationId === null ||
      (conversation.error instanceof ApiError && conversation.error.status === 404)
    ) {
      return (
        <EmptyState
          title="Conversation not found"
          description="It may have been deleted, or it doesn't belong to your account."
        />
      );
    }
    return (
      <ErrorState
        status={
          conversation.error instanceof ApiError ? conversation.error.status : undefined
        }
        message={
          conversation.error instanceof Error
            ? conversation.error.message
            : "Failed to load this conversation."
        }
        onRetry={() => conversation.refetch()}
      />
    );
  }

  const convo = conversation.data;
  if (!convo) return null;

  const turns = hydratedTurnsFrom(convo.messages ?? []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <RepoToolNav repositoryId={repositoryId} repoName={repo.name} active="conversations" />
        <div className="mt-2 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold">
              {convo.title ?? `Conversation #${convo.id}`}
            </h1>
            <p className="text-xs text-muted-foreground">
              Updated {new Date(convo.updated_at).toLocaleString()}
            </p>
          </div>
          <Button
            render={
              <Link href={`/repositories/${repositoryId}/ask?conversation=${convo.id}`} />
            }
          >
            Continue conversation
          </Button>
        </div>
      </div>

      {turns.length === 0 ? (
        <EmptyState
          title="No messages yet"
          description="This conversation doesn't have any messages."
        />
      ) : (
        <div className="flex flex-col gap-3">
          {turns.map((turn) => (
            <MessageBubble key={turn.id} turn={turn} />
          ))}
        </div>
      )}
    </div>
  );
}
