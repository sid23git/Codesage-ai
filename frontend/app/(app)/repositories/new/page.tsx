"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useCallback, useRef } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useCreateRepository } from "@/hooks/useRepositories";
import { ApiError } from "@/lib/api/client";
import {
  repositoryCreateSchema,
  type RepositoryCreateFormValues,
} from "@/lib/validation/repository";

export default function NewRepositoryPage() {
  const router = useRouter();
  const createRepository = useCreateRepository();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors },
  } = useForm<RepositoryCreateFormValues>({
    resolver: zodResolver(repositoryCreateSchema),
  });

  // A plain ref, not `createRepository.isPending`: two synchronous submits
  // (e.g. a fast double Enter-press) can both fire before React re-renders
  // with the mutation's new pending state, so a check against that state
  // would race. A ref is mutated immediately, with no render in between.
  const submitLock = useRef(false);

  // The ref is only ever read/written inside this memoized callback (never
  // during render itself), which is what `handleSubmit` invokes later, in
  // response to an actual submit event -- not at render time.
  const onValidSubmit = useCallback(
    async (values: RepositoryCreateFormValues) => {
      if (submitLock.current) return;
      submitLock.current = true;

      try {
        const repo = await createRepository.mutateAsync({
          name: values.name,
          github_url: values.github_url,
          description: values.description || undefined,
          primary_language: values.primary_language || undefined,
        });
        toast.success("Repository added.");
        router.push(`/repositories/${repo.id}`);
      } catch (error) {
        if (error instanceof ApiError && error.status === 409) {
          setError("github_url", {
            message: "This repository is already connected.",
          });
          return;
        }
        if (error instanceof ApiError && error.status === 422) {
          setError("github_url", { message: error.message });
          return;
        }
        const message =
          error instanceof ApiError ? error.message : "Unable to add repository.";
        toast.error(message);
      } finally {
        submitLock.current = false;
      }
    },
    [createRepository, router, setError],
  );

  // react-hook-form's `handleSubmit` wraps `onValidSubmit` and only ever
  // invokes it later, from the form's actual submit event -- never during
  // this render. The `react-hooks/refs` rule can't statically see through
  // that deferral and flags it as if the ref-reading callback ran now;
  // this is a verified false positive (see the double-submit-guard test
  // in __tests__/repository-new.test.tsx).
  // eslint-disable-next-line react-hooks/refs
  const onSubmit = handleSubmit(onValidSubmit);

  return (
    <div className="max-w-lg">
      <Card>
        <CardHeader>
          <CardTitle>Connect a repository</CardTitle>
          <CardDescription>
            Add a public GitHub repository to start asking questions about it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit} className="flex flex-col gap-4" noValidate>
            <div className="flex flex-col gap-2">
              <Label htmlFor="name">Name</Label>
              <Input id="name" placeholder="my-project" {...register("name")} />
              {errors.name ? (
                <p className="text-sm text-destructive">{errors.name.message}</p>
              ) : null}
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="github_url">GitHub URL</Label>
              <Input
                id="github_url"
                placeholder="https://github.com/owner/repo"
                {...register("github_url")}
              />
              {errors.github_url ? (
                <p className="text-sm text-destructive">
                  {errors.github_url.message}
                </p>
              ) : null}
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="description">Description (optional)</Label>
              <Input id="description" {...register("description")} />
              {errors.description ? (
                <p className="text-sm text-destructive">
                  {errors.description.message}
                </p>
              ) : null}
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="primary_language">Primary language (optional)</Label>
              <Input
                id="primary_language"
                placeholder="Python"
                {...register("primary_language")}
              />
              {errors.primary_language ? (
                <p className="text-sm text-destructive">
                  {errors.primary_language.message}
                </p>
              ) : null}
            </div>

            <Button type="submit" disabled={createRepository.isPending} className="mt-2">
              {createRepository.isPending ? "Adding…" : "Add repository"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
