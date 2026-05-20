"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { TrendingUp, Loader2, BarChart3, AlertCircle, Layers } from "lucide-react";
import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine } from "recharts";
import { experimentsApi, portfolioApi, PortfolioResult, Subset } from "@/lib/api";
import { MetricCard } from "@/components/ui/MetricCard";
import { cn } from "@/lib/utils";

const METHODS = [
  { id: "equal", label: "Equal Weight", desc: "Uniform signal weighting" },
  { id: "ic", label: "IC Weighted", desc: "Weight by historical IC" },
  { id: "risk_adj", label: "Risk Adjusted", desc: "IC / vol weighting" },
];

const fmt = (v: number | undefined, d = 2, pct = false) =>
  v == null ? "—" : pct ? `${(v * 100).toFixed(d)}%` : v.toFixed(d);

export default function PortfolioLabPage() {
  const [selectedExpId, setSelectedExpId] = useState<string | null>(null);
  const [selectedSubsetId, setSelectedSubsetId] = useState<string | null>(null);
  const [method, setMethod] = useState("ic");
  const [nQ, setNQ] = useState(10);
  const [result, setResult] = useState<PortfolioResult | null>(null);

  const { data: experiments = [] } = useQuery({ queryKey: ["experiments"], queryFn: experimentsApi.list });
  const completed = experiments.filter((e) => e.status === "completed");
  const { data: subsets = [] } = useQuery({ queryKey: ["subsets", selectedExpId], queryFn: () => experimentsApi.subsets(selectedExpId!, 20), enabled: !!selectedExpId });

  const backtestMutation = useMutation({
    mutationFn: () => { if (!selectedSubsetId) throw new Error("No subset"); return portfolioApi.backtest({ subset_id: selectedSubsetId, method, n_quantiles: nQ }); },
    onSuccess: (d) => { setResult(d); toast.success("Backtest complete"); },
    onError: (e: Error) => toast.error(e.message),
  });

  const cumData = result?.dates_ts?.map((d, i) => ({ date: d.slice(0, 10), val: (result.cumulative_returns_ts?.[i] ?? 0) * 100 })) ?? [];
  const ddData = result?.dates_ts?.map((d, i) => ({ date: d.slice(0, 10), dd: (result.drawdown_ts?.[i] ?? 0) * 100 })) ?? [];
  const lastVal = cumData[cumData.length - 1]?.val ?? 0;

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><TrendingUp className="w-6 h-6 text-primary" />Portfolio Lab</h1>
        <p className="text-sm text-muted-foreground mt-1">Combine discovered signals and run long-short backtests</p>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="space-y-4">
          <div className="quant-card">
            <h2 className="text-sm font-semibold mb-3">Experiment</h2>
            {completed.length === 0 ? <p className="text-xs text-muted-foreground">No completed experiments</p> : (
              <div className="space-y-1">
                {completed.map((exp) => (
                  <button key={exp.id} onClick={() => { setSelectedExpId(exp.id); setSelectedSubsetId(null); setResult(null); }} className={cn("w-full text-left px-3 py-2 rounded transition-colors text-sm", selectedExpId === exp.id ? "bg-primary/10 text-primary" : "hover:bg-secondary")}>{exp.name}</button>
                ))}
              </div>
            )}
          </div>
          {subsets.length > 0 && (
            <div className="quant-card">
              <h2 className="text-sm font-semibold mb-3 flex items-center gap-2"><Layers className="w-4 h-4 text-primary" />Feature Subset</h2>
              <div className="space-y-1 max-h-48 overflow-y-auto">
                {subsets.map((s: Subset, i: number) => (
                  <button key={s.id} onClick={() => { setSelectedSubsetId(s.id); setResult(null); }} className={cn("w-full text-left px-3 py-2 rounded transition-colors", selectedSubsetId === s.id ? "bg-primary/10 text-primary" : "hover:bg-secondary")}>
                    <p className="text-xs font-medium">Subset #{i + 1}</p>
                    <p className="text-[10px] text-muted-foreground">{s.feature_names?.length} features · IC {((s.relevance_score ?? 0) * 100).toFixed(1)}%</p>
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="quant-card">
            <h2 className="text-sm font-semibold mb-3">Signal Combination</h2>
            <div className="space-y-2">
              {METHODS.map((m) => (
                <button key={m.id} onClick={() => setMethod(m.id)} className={cn("w-full text-left px-3 py-2 rounded border transition-colors", method === m.id ? "border-primary/60 bg-primary/10" : "border-border hover:border-primary/30")}>
                  <p className="text-xs font-medium">{m.label}</p><p className="text-[10px] text-muted-foreground">{m.desc}</p>
                </button>
              ))}
            </div>
            <div className="mt-4">
              <label className="text-xs text-muted-foreground">Quantiles ({nQ})</label>
              <input type="range" min={5} max={20} value={nQ} onChange={(e) => setNQ(Number(e.target.value))} className="w-full mt-1 accent-primary" />
            </div>
            <button onClick={() => backtestMutation.mutate()} disabled={!selectedSubsetId || backtestMutation.isPending} className="w-full mt-4 flex items-center justify-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded text-sm font-medium hover:bg-primary/90 disabled:opacity-60 transition-colors">
              {backtestMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <BarChart3 className="w-4 h-4" />}Run Backtest
            </button>
          </div>
        </div>

        <div className="lg:col-span-2 space-y-4">
          {!result && !backtestMutation.isPending && (
            <div className="quant-card flex flex-col items-center justify-center py-20 text-muted-foreground"><TrendingUp className="w-10 h-10 mb-3 opacity-30" /><p className="text-sm">Configure and run a backtest</p></div>
          )}
          {backtestMutation.isPending && (
            <div className="quant-card flex items-center justify-center py-20 gap-3 text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin text-primary" /><p className="text-sm">Running backtest...</p></div>
          )}
          {result && <>
            <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
              {[["Sharpe", fmt(result.sharpe), true], ["Sortino", fmt(result.sortino), false], ["Max DD", fmt(result.max_drawdown, 2, true), false], ["Ann. Ret", fmt(result.annualized_return, 2, true), false], ["Calmar", fmt(result.calmar), false], ["Hit Rate", fmt(result.hit_rate, 2, true), false]].map(([l, v, h]) => (
                <div key={String(l)} className={cn("quant-card text-center py-3", h && "border-primary/40 bg-primary/5")}>
                  <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1">{l}</p>
                  <p className={cn("text-lg font-mono font-bold", h ? "text-primary" : "text-foreground")}>{v}</p>
                </div>
              ))}
            </div>
            {cumData.length > 0 && (
              <div className="quant-card">
                <h2 className="text-sm font-semibold mb-3">Cumulative Returns</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <AreaChart data={cumData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                    <defs><linearGradient id="cg" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor={lastVal >= 0 ? "#22d3ee" : "#f87171"} stopOpacity={0.2} /><stop offset="95%" stopColor={lastVal >= 0 ? "#22d3ee" : "#f87171"} stopOpacity={0} /></linearGradient></defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(222 30% 18%)" />
                    <XAxis dataKey="date" tick={{ fontSize: 9, fill: "hsl(215 20% 50%)" }} tickFormatter={(v) => v.slice(0, 7)} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 9, fill: "hsl(215 20% 50%)" }} tickFormatter={(v) => `${v.toFixed(0)}%`} />
                    <Tooltip contentStyle={{ background: "hsl(222 47% 10%)", border: "1px solid hsl(222 30% 18%)", fontSize: 11 }} formatter={(v: number) => [`${v.toFixed(2)}%`, "Cum. Return"]} />
                    <ReferenceLine y={0} stroke="hsl(215 20% 40%)" strokeDasharray="4 4" />
                    <Area type="monotone" dataKey="val" stroke={lastVal >= 0 ? "#22d3ee" : "#f87171"} fill="url(#cg)" strokeWidth={1.5} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
            {ddData.length > 0 && (
              <div className="quant-card">
                <h2 className="text-sm font-semibold mb-3">Drawdown</h2>
                <ResponsiveContainer width="100%" height={120}>
                  <AreaChart data={ddData} margin={{ top: 5, right: 10, bottom: 5, left: 0 }}>
                    <defs><linearGradient id="ddg" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#f87171" stopOpacity={0.3} /><stop offset="95%" stopColor="#f87171" stopOpacity={0} /></linearGradient></defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(222 30% 18%)" />
                    <XAxis dataKey="date" tick={{ fontSize: 9, fill: "hsl(215 20% 50%)" }} tickFormatter={(v) => v.slice(0, 7)} interval="preserveStartEnd" />
                    <YAxis tick={{ fontSize: 9, fill: "hsl(215 20% 50%)" }} tickFormatter={(v) => `${v.toFixed(0)}%`} />
                    <Tooltip contentStyle={{ background: "hsl(222 47% 10%)", border: "1px solid hsl(222 30% 18%)", fontSize: 11 }} formatter={(v: number) => [`${v.toFixed(2)}%`, "Drawdown"]} />
                    <Area type="monotone" dataKey="dd" stroke="#f87171" fill="url(#ddg)" strokeWidth={1.5} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </>}
          {backtestMutation.isError && (
            <div className="quant-card flex items-center gap-3 text-red-400 py-6"><AlertCircle className="w-5 h-5" /><p className="text-sm">{(backtestMutation.error as Error).message}</p></div>
          )}
        </div>
      </div>
    </div>
  );
}
