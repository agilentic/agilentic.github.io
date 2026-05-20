"use client";

import { cn } from "@/lib/utils";
import { LucideIcon } from "lucide-react";

interface MetricCardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon?: LucideIcon;
  trend?: "up" | "down" | "neutral";
  trendValue?: string;
  className?: string;
  loading?: boolean;
}

export function MetricCard({ title, value, subtitle, icon: Icon, trend, trendValue, className, loading }: MetricCardProps) {
  return (
    <div className={cn("quant-card", className)}>
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{title}</p>
          {loading ? (
            <div className="h-7 w-24 bg-muted rounded animate-pulse" />
          ) : (
            <p className="text-2xl font-bold font-mono tracking-tight">{value}</p>
          )}
          {subtitle && <p className="text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        {Icon && (
          <div className="p-2 bg-primary/10 rounded-md">
            <Icon className="w-4 h-4 text-primary" />
          </div>
        )}
      </div>
      {trendValue && (
        <div className="mt-3 flex items-center gap-1.5 text-xs">
          <span className={cn(trend === "up" && "text-green-400", trend === "down" && "text-red-400", trend === "neutral" && "text-muted-foreground")}>
            {trendValue}
          </span>
        </div>
      )}
    </div>
  );
}
