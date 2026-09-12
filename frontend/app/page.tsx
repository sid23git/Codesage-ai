import Link from "next/link";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export default function LandingPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 px-4 text-center">
      <div className="flex flex-col gap-3">
        <h1 className="text-3xl font-semibold tracking-tight">CodeSage AI</h1>
        <p className="max-w-md text-muted-foreground">
          An AI-powered software engineering assistant that understands,
          explains, and reviews your GitHub repositories -- grounded in
          your actual code, with every answer cited to its source.
        </p>
      </div>
      <div className="flex gap-3">
        <Link href="/register" className={cn(buttonVariants({ variant: "default" }))}>
          Get started
        </Link>
        <Link href="/login" className={cn(buttonVariants({ variant: "outline" }))}>
          Sign in
        </Link>
      </div>
    </div>
  );
}
