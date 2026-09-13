"use client";

import Link from "next/link";

import { cn } from "@/lib/utils";

const TOOLS = [
  { key: "ask", label: "Ask", href: (id: number) => `/repositories/${id}/ask` },
  { key: "explain", label: "Explain", href: (id: number) => `/repositories/${id}/explain` },
  { key: "review", label: "Review", href: (id: number) => `/repositories/${id}/review` },
] as const;

/** Shared header for the Ask/Explain/Review pages: a link back to the
 * repository overview plus tabs between the three AI tools, so moving
 * between them (or back out) is always one click away. */
export function RepoToolNav({
  repositoryId,
  repoName,
  active,
}: {
  repositoryId: number;
  repoName: string;
  active: "ask" | "explain" | "review";
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Link
        href={`/repositories/${repositoryId}`}
        className="text-sm text-muted-foreground underline"
      >
        ← {repoName}
      </Link>
      <nav aria-label="AI tools" className="flex gap-1">
        {TOOLS.map((tool) => (
          <Link
            key={tool.key}
            href={tool.href(repositoryId)}
            aria-current={active === tool.key ? "page" : undefined}
            className={cn(
              "rounded-md px-2.5 py-1 text-sm font-medium transition-colors",
              active === tool.key
                ? "bg-muted text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
            )}
          >
            {tool.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}
