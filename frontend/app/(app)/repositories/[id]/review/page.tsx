"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";

import { EvidenceList } from "@/components/evidence/EvidenceList";
import { RepoToolNav } from "@/components/layout/RepoToolNav";
import { MarkdownRenderer } from "@/components/markdown/MarkdownRenderer";
import { FindingCard } from "@/components/review/FindingCard";
import { EmptyState } from "@/components/states/EmptyState";
import { ErrorState } from "@/components/states/ErrorState";
import { InsufficientEvidenceNotice } from "@/components/states/InsufficientEvidenceNotice";
import { LoadingState } from "@/components/states/LoadingState";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useReview } from "@/hooks/useAssistant";
import { useRepository } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { toEvidenceViews } from "@/lib/api/evidence";
import type { ReviewRequest } from "@/lib/api/types";
import {
  MAX_USER_CODE_CHARS,
  reviewFocusValues,
  reviewSchema,
  type ReviewFormValues,
} from "@/lib/validation/review";

export default function ReviewPage() {
  const params = useParams<{ id: string }>();
  const repositoryId = Number(params.id);
  const searchParams = useSearchParams();
  const conversationId = (() => {
    const raw = searchParams.get("conversation");
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : undefined;
  })();

  const repository = useRepository(repositoryId);
  const review = useReview(repositoryId);
  const [lastPayload, setLastPayload] = useState<ReviewRequest | null>(null);

  const {
    register,
    handleSubmit,
    control,
    formState: { errors },
  } = useForm<ReviewFormValues>({
    resolver: zodResolver(reviewSchema),
    defaultValues: {
      file_path: "",
      symbol: "",
      start_line: "",
      end_line: "",
      focus: "general",
      user_code: "",
    },
  });

  const userCode = useWatch({ control, name: "user_code" });
  const userCodeLength = userCode?.length ?? 0;

  const submitPayload = (values: ReviewFormValues) => {
    const payload: ReviewRequest = {
      file_path: values.file_path || undefined,
      symbol: values.symbol || undefined,
      start_line: values.start_line ? Number(values.start_line) : undefined,
      end_line: values.end_line ? Number(values.end_line) : undefined,
      focus: values.focus,
      user_code: values.user_code || undefined,
      conversation_id: conversationId,
    };
    setLastPayload(payload);
    review.mutate(payload);
  };

  const onSubmit = handleSubmit(submitPayload);
  const onRetry = () => {
    if (lastPayload) review.mutate(lastPayload);
  };

  // A malformed URL (e.g. /repositories/abc/review) disables every
  // query below rather than erroring, so without this guard the page
  // would fall through every check and render nothing -- a permanent
  // blank screen instead of a clear "not found."
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

  const evidence = toEvidenceViews(review.data?.evidence ?? []);
  const evidenceByChunkId = new Map(evidence.map((item) => [item.chunkId, item]));
  const usedUserCode = Boolean(lastPayload?.user_code);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <RepoToolNav repositoryId={repositoryId} repoName={repo.name} active="review" />
        <h1 className="mt-2 text-xl font-semibold">Review</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">What should I review?</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-2">
              <Label htmlFor="file_path">File path (repository target)</Label>
              <Input
                id="file_path"
                placeholder="app/services/auth.py"
                {...register("file_path")}
              />
              {errors.file_path ? (
                <p className="text-sm text-destructive">{errors.file_path.message}</p>
              ) : null}
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div className="flex flex-col gap-2">
                <Label htmlFor="symbol">Symbol (optional)</Label>
                <Input id="symbol" {...register("symbol")} />
                {errors.symbol ? (
                  <p className="text-sm text-destructive">{errors.symbol.message}</p>
                ) : null}
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="start_line">Start line (optional)</Label>
                <Input id="start_line" inputMode="numeric" {...register("start_line")} />
                {errors.start_line ? (
                  <p className="text-sm text-destructive">{errors.start_line.message}</p>
                ) : null}
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="end_line">End line (optional)</Label>
                <Input id="end_line" inputMode="numeric" {...register("end_line")} />
                {errors.end_line ? (
                  <p className="text-sm text-destructive">{errors.end_line.message}</p>
                ) : null}
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="focus">Focus</Label>
              <select
                id="focus"
                className="h-8 w-fit rounded-lg border border-input bg-transparent px-2.5 text-sm"
                {...register("focus")}
              >
                {reviewFocusValues.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="user_code">
                  Or paste code/diff to review (untrusted input, not repository evidence)
                </Label>
                <span
                  className={
                    userCodeLength > MAX_USER_CODE_CHARS
                      ? "text-xs text-destructive"
                      : "text-xs text-muted-foreground"
                  }
                >
                  {userCodeLength.toLocaleString()} / {MAX_USER_CODE_CHARS.toLocaleString()}
                </span>
              </div>
              <Textarea
                id="user_code"
                rows={6}
                className="font-mono text-xs"
                placeholder="Paste a snippet or diff…"
                {...register("user_code")}
              />
              {errors.user_code ? (
                <p className="text-sm text-destructive">{errors.user_code.message}</p>
              ) : null}
            </div>

            <Button type="submit" disabled={review.isPending} className="w-fit">
              {review.isPending ? "Reviewing…" : "Review"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {review.isPending ? <LoadingState rows={3} /> : null}

      {review.isError ? (
        <ErrorState
          status={review.error instanceof ApiError ? review.error.status : undefined}
          message={apiErrorMessage(review.error)}
          onRetry={onRetry}
        />
      ) : null}

      {review.isSuccess && review.data.status === "insufficient_evidence" ? (
        <InsufficientEvidenceNotice
          message={
            review.data.summary ||
            "I couldn't find enough relevant, sufficiently-confident evidence for this target."
          }
        />
      ) : null}

      {review.isSuccess && review.data.status !== "insufficient_evidence" ? (
        <div className="flex flex-col gap-4">
          {usedUserCode ? (
            <p className="text-xs text-muted-foreground">
              This review covers the user-provided code above (untrusted input), with
              indexed repository evidence used only as supporting context where relevant.
            </p>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle className="text-base">Summary</CardTitle>
            </CardHeader>
            <CardContent>
              <MarkdownRenderer content={review.data.summary} />
            </CardContent>
          </Card>

          {review.data.findings && review.data.findings.length > 0 ? (
            <div className="flex flex-col gap-3">
              <h2 className="text-sm font-medium text-muted-foreground">
                Findings ({review.data.findings.length})
              </h2>
              {review.data.findings.map((finding, index) => (
                <FindingCard
                  key={index}
                  finding={finding}
                  evidenceByChunkId={evidenceByChunkId}
                />
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No findings -- looks clean.</p>
          )}

          <EvidenceList evidence={evidence} />
        </div>
      ) : null}
    </div>
  );
}
