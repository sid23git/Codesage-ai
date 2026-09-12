import { Badge } from "@/components/ui/badge";

/**
 * Renders any repository or ingestion status string with a consistent
 * color mapping. Backend values (see app/schemas/ingestion.py::
 * IngestionStatus and app/schemas/repository.py::RepositoryStatus):
 * pending | ingesting | analyzing | ready | completed | failed
 */
const VARIANT_BY_STATUS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  pending: "outline",
  ingesting: "secondary",
  analyzing: "secondary",
  ready: "default",
  completed: "default",
  failed: "destructive",
};

export function StatusBadge({ status }: { status: string }) {
  const variant = VARIANT_BY_STATUS[status] ?? "outline";
  return <Badge variant={variant}>{status}</Badge>;
}
