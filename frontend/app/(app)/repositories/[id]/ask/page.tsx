"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import {
  useParams,
  usePathname,
  useRouter,
  useSearchParams,
} from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";

import { ConversationThread } from "@/components/chat/ConversationThread";
import { hydratedTurnsFrom, type ChatTurn } from "@/components/chat/types";
import { RepoToolNav } from "@/components/layout/RepoToolNav";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { LoadingState } from "@/components/states/LoadingState";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAsk, useConversation } from "@/hooks/useAssistant";
import { useRepository } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { toEvidenceViews } from "@/lib/api/evidence";
import { askMessageSchema, type AskMessageFormValues } from "@/lib/validation/ask";

let turnCounter = 0;
function nextTurnId(prefix: string) {
  turnCounter += 1;
  return `${prefix}-${turnCounter}`;
}

export default function AskPage() {
  const params = useParams<{ id: string }>();
  const repositoryId = Number(params.id);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  const initialConversationId = (() => {
    const raw = searchParams.get("conversation");
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : null;
  })();
  const [conversationId, setConversationId] = useState<number | null>(
    initialConversationId,
  );

  const repository = useRepository(repositoryId);
  const conversation = useConversation(repositoryId, initialConversationId);
  const ask = useAsk(repositoryId);

  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const hydratedRef = useRef(false);
  useEffect(() => {
    if (hydratedRef.current) return;
    if (initialConversationId === null) {
      hydratedRef.current = true;
      return;
    }
    if (conversation.data) {
      setTurns(hydratedTurnsFrom(conversation.data.messages ?? []));
      hydratedRef.current = true;
    }
  }, [conversation.data, initialConversationId]);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<AskMessageFormValues>({
    resolver: zodResolver(askMessageSchema),
    // Without an explicit default, reset() has no defined target to
    // clear the (uncontrolled) textarea back to, so the previous
    // question's text would still be there for the next one to build on
    // top of -- confirmed by a multi-turn test that typed a second
    // question and got the first one prepended to it.
    defaultValues: { message: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    const userTurn: ChatTurn = {
      id: nextTurnId("user"),
      role: "user",
      content: values.message,
    };
    setTurns((prev) => [...prev, userTurn]);
    reset();

    try {
      const response = await ask.mutateAsync({
        message: values.message,
        conversation_id: conversationId ?? undefined,
      });

      if (conversationId === null) {
        setConversationId(response.conversation_id);
        router.replace(`${pathname}?conversation=${response.conversation_id}`);
      }

      setTurns((prev) => [
        ...prev,
        {
          id: nextTurnId("assistant"),
          role: "assistant",
          status: response.status === "insufficient_evidence" ? "insufficient_evidence" : "answered",
          content: response.answer,
          evidence: toEvidenceViews(response.evidence ?? []),
          model: response.model,
        },
      ]);
    } catch (error) {
      setTurns((prev) => [
        ...prev,
        {
          id: nextTurnId("error"),
          role: "assistant-error",
          status: error instanceof ApiError ? error.status : undefined,
          message: apiErrorMessage(error),
        },
      ]);
    }
  });

  // A malformed URL (e.g. /repositories/abc/ask) disables every query
  // below rather than erroring, so without this guard the page would
  // fall through every check and render nothing -- a permanent blank
  // screen instead of a clear "not found."
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
    <div className="flex h-[calc(100vh-6.5rem)] flex-col gap-4">
      <div>
        <RepoToolNav repositoryId={repositoryId} repoName={repo.name} active="ask" />
        <h1 className="mt-2 text-xl font-semibold">Ask</h1>
      </div>

      <ConversationThread
        turns={turns}
        isAsking={ask.isPending}
        isHydrating={initialConversationId !== null && conversation.isLoading}
      />

      <form onSubmit={onSubmit} className="flex flex-col gap-2" noValidate>
        <div className="flex gap-2">
          <Textarea
            aria-label="Ask a question about this repository"
            placeholder="Ask a question about this repository…"
            rows={2}
            disabled={ask.isPending}
            className="resize-none"
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                onSubmit();
              }
            }}
            {...register("message")}
          />
          <Button type="submit" disabled={ask.isPending} className="self-end">
            {ask.isPending ? "Asking…" : "Send"}
          </Button>
        </div>
        {errors.message ? (
          <p className="text-sm text-destructive">{errors.message.message}</p>
        ) : null}
      </form>
    </div>
  );
}
