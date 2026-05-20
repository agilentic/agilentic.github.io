import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatNumber(n: number, decimals = 0): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(decimals);
}

export function formatPercent(n: number, decimals = 2): string {
  return `${(n * 100).toFixed(decimals)}%`;
}

export function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function statusBadgeColor(status: string): string {
  switch (status) {
    case "running": return "border-blue-500/40 bg-blue-500/10 text-blue-400";
    case "completed": return "border-green-500/40 bg-green-500/10 text-green-400";
    case "failed": return "border-red-500/40 bg-red-500/10 text-red-400";
    case "stopped": return "border-yellow-500/40 bg-yellow-500/10 text-yellow-400";
    default: return "border-border bg-secondary text-muted-foreground";
  }
}
