import { cn, statusBadgeColor } from "@/lib/utils";

interface StatusBadgeProps { status: string; size?: "sm" | "md"; }

const STATUS_LABELS: Record<string, string> = {
  completed: "Completed", running: "Running", failed: "Failed",
  stopped: "Stopped", pending: "Pending", paused: "Paused", ready: "Ready",
};

export function StatusBadge({ status, size = "sm" }: StatusBadgeProps) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border font-medium", size === "sm" ? "text-xs px-2 py-0.5" : "text-sm px-3 py-1", statusBadgeColor(status))}>
      <span className={cn("inline-block rounded-full", size === "sm" ? "w-1.5 h-1.5" : "w-2 h-2",
        status === "running" && "animate-pulse bg-blue-400",
        status === "completed" && "bg-green-400",
        status === "failed" && "bg-red-400",
        status === "stopped" && "bg-yellow-400",
        !["running","completed","failed","stopped"].includes(status) && "bg-muted-foreground"
      )} />
      {STATUS_LABELS[status] || status}
    </span>
  );
}
