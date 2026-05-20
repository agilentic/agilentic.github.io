"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, Database, FlaskConical, TrendingUp,
  Network, BarChart3, FileText, ChevronLeft, ChevronRight, Atom, Activity,
} from "lucide-react";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/data-studio", label: "Data Studio", icon: Database },
  { href: "/feature-lab", label: "Feature Lab", icon: FlaskConical },
  { href: "/evolution-monitor", label: "Evolution Monitor", icon: Activity },
  { href: "/synergy-explorer", label: "Synergy Explorer", icon: Network },
  { href: "/portfolio-lab", label: "Portfolio Lab", icon: TrendingUp },
  { href: "/experiments", label: "Experiments", icon: FileText },
];

export function AppLayout({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const pathname = usePathname();

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className={cn("flex flex-col bg-card border-r border-border transition-all duration-200 z-50", collapsed ? "w-14" : "w-56")}>
        <div className="flex items-center gap-3 px-4 py-4 border-b border-border h-14">
          <div className="flex items-center justify-center w-7 h-7 rounded bg-primary/10 text-primary flex-shrink-0">
            <Atom className="w-4 h-4" />
          </div>
          {!collapsed && <span className="font-semibold text-sm tracking-tight whitespace-nowrap">FactorDiscover</span>}
        </div>
        <nav className="flex-1 overflow-y-auto py-3 px-2 space-y-0.5">
          {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
            const active = pathname === href || (href !== "/" && pathname.startsWith(href));
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors",
                  active ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                )}
                title={collapsed ? label : undefined}
              >
                <Icon className={cn("w-4 h-4 flex-shrink-0", active && "text-primary")} />
                {!collapsed && <span className="truncate">{label}</span>}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-border p-2">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="flex items-center justify-center w-full h-8 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors"
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto">
        <div className="min-h-full">{children}</div>
      </main>
    </div>
  );
}
