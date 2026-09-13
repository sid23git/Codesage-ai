"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";

import { RepoToolNav } from "@/components/layout/RepoToolNav";
import { EvidenceList } from "@/components/evidence/EvidenceList";
import { ErrorState } from "@/components/states/ErrorState";
import { InsufficientEvidenceNotice } from "@/components/states/InsufficientEvidenceNotice";
import { LoadingState } from "@/components/states/LoadingState";
import { MarkdownRenderer } from "@/components/markdown/MarkdownRenderer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useExplain } from "@/hooks/useAssistant";
import { useRepository } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";
import { apiErrorMessage } from "@/lib/api/errors";
import { toEvidenceViews } from "@/lib/api/evidence";
import type { ExplainRequest } from "@/lib/api/types";
import { explainSchema, type ExplainFormValues } from "@/lib/validation/explain";

export default function ExplainPage() {
  const params = useParams<{ id: string }>();
  const repositoryId = Number(params.id);
  const searchParams = useSearchParams();
  const conversationId = (() => {
    const raw = searchParams.get("conversation");
    const parsed = raw ? Number(raw) : NaN;
    return Number.isFinite(parsed) ? parsed : undefined;
  })();

  const repository = useRepository(repositoryId);
  const explain = useExplain(repositoryId);
  const [lastPayload, setLastPayload] = useState<ExplainRequest | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ExplainFormValues>({
    resolver: zodResolver(explainSchema),
    defaultValues: { file_path: "", symbol: "", start_line: "", end_line: "", question: "" },
  });

  const submitPayload = (values: ExplainFormValues) => {
    const payload: ExplainRequest = {
      file_path: values.file_path,
      symbol: values.symbol || undefined,
      start_line: values.start_line ? Number(values.start_line) : undefined,
      end_line: values.end_line ? Number(values.end_line) : undefined,
      question: values.question || undefined,
      conversation_id: conversationId,
    };
    setLastPayload(payload);
    explain.mutate(payload);
  };

  const onSubmit = handleSubmit(submitPayload);
  const onRetry = () => {
    if (lastPayload) explain.mutate(lastPayload);
  };

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

  const evidence = toEvidenceViews(explain.data?.evidence ?? []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <RepoToolNav repositoryId={repositoryId} repoName={repo.name} active="explain" />
        <h1 className="mt-2 text-xl font-semibold">Explain</h1>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">What should I explain?</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-2">
              <Label htmlFor="file_path">File path</Label>
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
                <Input id="symbol" placeholder="create_access_token" {...register("symbol")} />
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
              <Label htmlFor="question">Question or focus (optional)</Label>
              <Textarea
                id="question"
                rows={2}
                placeholder="Does this validate the input before using it?"
                {...register("question")}
              />
              {errors.question ? (
                <p className="text-sm text-destructive">{errors.question.message}</p>
              ) : null}
            </div>

            <Button type="submit" disabled={explain.isPending} className="w-fit">
              {explain.isPending ? "Explaining…" : "Explain"}
            </Button>
          </form>
        </CardContent>
      </Card>

      {explain.isPending ? <LoadingState rows={3} /> : null}

      {explain.isError ? (
        <ErrorState
          status={explain.error instanceof ApiError ? explain.error.status : undefined}
          message={apiErrorMessage(explain.error)}
          onRetry={onRetry}
        />
      ) : null}

      {explain.isSuccess && explain.data.status === "insufficient_evidence" ? (
        <InsufficientEvidenceNotice
          message={
            explain.data.explanation ||
            "I couldn't find enough relevant, sufficiently-confident evidence for this target."
          }
        />
      ) : null}

      {explain.isSuccess && explain.data.status !== "insufficient_evidence" ? (
        <Card>
          <CardContent className="flex flex-col gap-4 pt-6">
            <MarkdownRenderer content={explain.data.explanation} />
            <EvidenceList evidence={evidence} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
