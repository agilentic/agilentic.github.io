"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { Activity, Atom, BarChart3, Database, FlaskConical, Network, Play, TrendingUp, Zap } from "lucide-react";
import { experimentsApi, datasetsApi } from "@/lib/api";
import { MetricCard } from "@/components/ui/MetricCard";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { formatNumber, relativeTime } from "@/lib/utils";

export default function DashboardPage() {
  const router = useRouter();

  const { data: experiments = [], isLoading: expLoading } = useQuery({
    queryKey: ["experiments"],
    queryFn: experimentsApi.list,
    refetchInterval: 5000,
  });

  const { data: datasets = [], isLoading: dsLoading } = useQuery({
    queryKey: ["datasets"],
    queryFn: datasetsApi.list,
  });

  const runningExps = experiments.filter(e => e.status === "running");
  const completedExps = experiments.filter(e => e.status === "completed");

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Atom className="w-6 h-6 text-primary" />
            Factor Discovery Platform
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Multi-objective evolutionary optimization for alpha discovery</p>
        </div>
        <button onClick={() => router.push("/experiments")} className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium hover:bg-primary/90 transition-colors">
          <Play className="w-4 h-4" />
          New Experiment
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard title="Total Experiments" value={experiments.length} icon={Activity} loading={expLoading} />
        <MetricCard title="Running" value={runningExps.length} icon={Zap} loading={expLoading} trend={runningExps.length > 0 ? "up" : "neutral"} trendValue={runningExps.length > 0 ? "Active now" : "Idle"} />
        <MetricCard title="Completed" value={completedExps.length} icon={BarChart3} loading={expLoading} />
        <MetricCard title="Datasets" value={datasets.length} icon={Database} loading={dsLoading} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="quant-card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold">Recent Experiments</h2>
            <button onClick={() => router.push("/experiments")} className="text-xs text-primary hover:text-primary/80">View all →</button>
          </div>
          {expLoading ? (
            <div className="space-y-3">{[1,2,3].map(i => <div key={i} className="h-12 bg-muted rounded animate-pulse" />)}</div>
          ) : experiments.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Activity className="w-8 h-8 mx-auto mb-2 opacity-50" />
              <p className="text-sm">No experiments yet.</p>
              <button onClick={() => router.push("/experiments")} className="mt-3 text-primary text-xs hover:underline">Run your first experiment →</button>
            </div>
          ) : (
            <div className="space-y-2">
              {experiments.slice(0, 6).map(exp => (
                <div key={exp.id} className="flex items-center justify-between py-2.5 px-3 rounded-md hover:bg-secondary cursor-pointer transition-colors" onClick={() => router.push(`/evolution-monitor?id=${exp.id}`)}>
                  <div className="min-w-0">
                    <p className="text-sm font-medium truncate">{exp.name}</p>
                    <p className="text-xs text-muted-foreground">{relativeTime(exp.created_at)} · {exp.target_col}</p>
                  </div>
                  <div className="flex items-center gap-3 ml-3">
                    {exp.status === "running" && <span className="text-xs text-muted-foreground font-mono">{Math.round(exp.progress * 100)}%</span>}
                    <StatusBadge status={exp.status} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="quant-card">
          <h2 className="text-sm font-semibold mb-4">Quick Start</h2>
          <div className="space-y-2">
            {[
              { icon: Database, title: "Load Sample Data", desc: "50 assets × 3 years of synthetic OHLCV", action: () => router.push("/data-studio"), color: "text-blue-400" },
              { icon: FlaskConical, title: "Browse Feature Library", desc: "Explore 120+ primitive operators and DSL", action: () => router.push("/feature-lab"), color: "text-purple-400" },
              { icon: Activity, title: "Run Evolutionary Search", desc: "NSGA-II + GP to find optimal feature subsets", action: () => router.push("/experiments"), color: "text-green-400" },
              { icon: Network, title: "Explore Synergies", desc: "Nonlinear feature interaction analysis", action: () => router.push("/synergy-explorer"), color: "text-orange-400" },
              { icon: TrendingUp, title: "Build Portfolio", desc: "Combine signals and backtest performance", action: () => router.push("/portfolio-lab"), color: "text-yellow-400" },
            ].map(({ icon: Icon, title, desc, action, color }) => (
              <button key={title} onClick={action} className="w-full flex items-start gap-3 p-3 rounded-md text-left hover:bg-secondary transition-colors group">
                <Icon className={`w-5 h-5 mt-0.5 ${color} flex-shrink-0`} />
                <div>
                  <p className="text-sm font-medium group-hover:text-primary transition-colors">{title}</p>
                  <p className="text-xs text-muted-foreground">{desc}</p>
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="quant-card">
        <h2 className="text-sm font-semibold mb-3">Platform Overview</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs text-muted-foreground">
          <div><p className="font-medium text-foreground mb-1">Optimization</p><p>NSGA-II multi-objective</p><p>6 fitness objectives</p><p>Pareto frontier tracking</p></div>
          <div><p className="font-medium text-foreground mb-1">Feature Discovery</p><p>120+ primitive operators</p><p>GP expression evolution</p><p>Factor DSL evaluator</p></div>
          <div><p className="font-medium text-foreground mb-1">Metrics</p><p>Spearman IC / ICIR</p><p>Distance correlation</p><p>Conditional MI synergy</p></div>
          <div><p className="font-medium text-foreground mb-1">Portfolio</p><p>IC-weighted signals</p><p>Long-short backtests</p><p>Walk-forward validation</p></div>
        </div>
      </div>
    </div>
  );
}
