"use client";

import { useEffect, useRef } from "react";

import { MessageBubble } from "@/components/chat/MessageBubble";
import { EmptyState } from "@/components/states/EmptyState";
import { LoadingState } from "@/components/states/LoadingState";
import type { ChatTurn } from "@/components/chat/types";

export function ConversationThread({
  turns,
  isAsking,
  isHydrating,
}: {
  turns: ChatTurn[];
  isAsking: boolean;
  isHydrating: boolean;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [turns.length, isAsking]);

  if (isHydrating) {
    return <LoadingState rows={3} />;
  }

  if (turns.length === 0) {
    return (
      <EmptyState
        title="Ask anything about this repository"
        description="Questions are answered using only what's actually been indexed, with sources cited for every claim."
      />
    );
  }

  return (
    <div
      className="flex flex-1 flex-col gap-3 overflow-y-auto"
      role="log"
      aria-live="polite"
      aria-label="Conversation"
    >
      {turns.map((turn) => (
        <MessageBubble key={turn.id} turn={turn} />
      ))}
      {isAsking ? (
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-lg border border-border bg-card px-3 py-2 text-sm text-muted-foreground">
            Thinking…
          </div>
        </div>
      ) : null}
      <div ref={bottomRef} />
    </div>
  );
}
