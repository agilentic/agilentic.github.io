"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Network, Info, ArrowRight, Layers } from "lucide-react";
import { experimentsApi, Subset } from "@/lib/api";
import { cn } from "@/lib/utils";

function SynergyHeatmap({ features, matrix }: { features: string[]; matrix: Record<string, Record<string, number>> }) {
  const [hovered, setHovered] = useState<{ row: string; col: string; value: number } | null>(null);
  if (!features.length) return null;
  const getColor = (v: number) => {
    const abs = Math.min(Math.abs(v) / 0.5, 1);
    return v > 0 ? `rgba(34,211,238,${0.1 + abs * 0.7})` : `rgba(248,113,113,${0.1 + abs * 0.7})`;
  };
  return (
    <div className="relative overflow-auto">
      <table className="text-[10px] border-collapse">
        <thead>
          <tr>
            <th className="w-20 sticky left-0 bg-card z-10" />
            {features.map((f) => <th key={f} className="text-center pb-2 font-mono font-normal text-muted-foreground" style={{ minWidth: 32, writingMode: "vertical-rl", transform: "rotate(180deg)", height: 56 }}>{f.length > 10 ? f.slice(0, 10) + "…" : f}</th>)}
          </tr>
        </thead>
        <tbody>
          {features.map((row) => (
            <tr key={row}>
              <td className="text-right pr-2 font-mono text-muted-foreground sticky left-0 bg-card z-10 whitespace-nowrap py-0.5">{row.length > 12 ? row.slice(0, 12) + "…" : row}</td>
              {features.map((col) => {
                const val = matrix[row]?.[col] ?? 0;
                return <td key={col} className="cursor-pointer hover:opacity-80" style={{ background: getColor(val), width: 32, height: 24, border: "1px solid hsl(222 30% 12%)" }} onMouseEnter={() => setHovered({ row, col, value: val })} onMouseLeave={() => setHovered(null)} />;
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {hovered && (
        <div className="absolute top-2 right-2 bg-card border border-border rounded px-3 py-2 text-xs pointer-events-none z-20">
          <p className="font-mono text-primary">{hovered.row}</p>
          <p className="font-mono text-muted-foreground">↕ {hovered.col}</p>
          <p className="font-mono font-bold mt-1">CMI = {hovered.value.toFixed(4)}</p>
        </div>
      )}
    </div>
  );
}

export default function SynergyExplorerPage() {
  const [selectedExpId, setSelectedExpId] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const { data: experiments = [] } = useQuery({ queryKey: ["experiments"], queryFn: experimentsApi.list });
  const completed = experiments.filter((e) => e.status === "completed");
  const { data: subsets = [], isLoading } = useQuery({ queryKey: ["subsets", selectedExpId], queryFn: () => experimentsApi.subsets(selectedExpId!, 20), enabled: !!selectedExpId });
  const { data: paretoData } = useQuery({ queryKey: ["pareto", selectedExpId], queryFn: () => experimentsApi.pareto(selectedExpId!), enabled: !!selectedExpId });
  const selected: Subset | null = subsets[selectedIdx] ?? null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const matrix = (paretoData as any)?.synergy_matrix ?? {};
  const matFeats = Object.keys(matrix);

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold flex items-center gap-2"><Network className="w-6 h-6 text-primary" />Synergy Explorer</h1>
        <p className="text-sm text-muted-foreground mt-1">Nonlinear feature interaction analysis via conditional mutual information</p>
      </div>
      <div className="quant-card">
        <h2 className="text-sm font-semibold mb-3">Select Completed Experiment</h2>
        {completed.length === 0 ? <p className="text-sm text-muted-foreground">No completed experiments yet.</p> : (
          <div className="flex flex-wrap gap-2">
            {completed.map((exp) => (
              <button key={exp.id} onClick={() => { setSelectedExpId(exp.id); setSelectedIdx(0); }} className={cn("px-3 py-1.5 rounded border text-sm transition-colors", selectedExpId === exp.id ? "border-primary/60 bg-primary/10 text-primary" : "border-border hover:border-primary/30")}>{exp.name}</button>
            ))}
          </div>
        )}
      </div>
      {selectedExpId && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="quant-card">
            <h2 className="text-sm font-semibold mb-3 flex items-center gap-2"><Layers className="w-4 h-4 text-primary" />Feature Subsets</h2>
            {isLoading ? [1, 2, 3].map((i) => <div key={i} className="h-10 bg-muted rounded animate-pulse mb-1" />) : subsets.length === 0 ? <p className="text-sm text-muted-foreground">No subsets</p> : (
              <div className="space-y-1">
                {subsets.map((s: Subset, i: number) => (
                  <button key={s.id} onClick={() => setSelectedIdx(i)} className={cn("w-full text-left px-3 py-2 rounded transition-colors", selectedIdx === i ? "bg-primary/10 text-primary" : "hover:bg-secondary")}>
                    <p className="text-xs font-medium">Subset #{i + 1}</p>
                    <p className="text-[10px] text-muted-foreground">{s.feature_names?.length ?? 0} features · {(s.composite_score ?? 0).toFixed(3)}</p>
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="space-y-4">
            {selected ? (
              <div className="quant-card">
                <h2 className="text-sm font-semibold mb-3 flex items-center gap-2"><ArrowRight className="w-4 h-4 text-primary" />Subset #{selectedIdx + 1}</h2>
                <div className="flex flex-wrap gap-1 mb-4">
                  {(selected.feature_names ?? []).map((f) => <span key={f} className="text-xs bg-primary/10 text-primary border border-primary/20 rounded px-2 py-1 font-mono">{f}</span>)}
                </div>
                <div className="space-y-2">
                  {[["Relevance", selected.relevance_score, "bg-cyan-400"], ["Synergy", selected.synergy_score, "bg-purple-400"], ["Stability", selected.stability_score, "bg-green-400"], ["Portfolio", selected.portfolio_score, "bg-yellow-400"]].map(([l, v, c]) => (
                    <div key={String(l)}>
                      <div className="flex justify-between text-xs mb-1"><span className="text-muted-foreground">{l}</span><span className="font-mono">{v != null ? ((v as number) * 100).toFixed(1) + "%" : "—"}</span></div>
                      <div className="h-1.5 bg-secondary rounded-full overflow-hidden"><div className={cn("h-full rounded-full", String(c))} style={{ width: `${Math.max(0, Math.min(1, (v as number) ?? 0)) * 100}%` }} /></div>
                    </div>
                  ))}
                </div>
              </div>
            ) : <div className="quant-card flex items-center justify-center py-16 text-muted-foreground text-sm">Select a subset</div>}
            <div className="quant-card bg-primary/5 border-primary/20">
              <div className="flex items-start gap-2">
                <Info className="w-4 h-4 text-primary mt-0.5 flex-shrink-0" />
                <div className="text-xs text-muted-foreground space-y-1">
                  <p><span className="text-foreground font-medium">Synergy</span> = CMI: I(f; y | S)</p>
                  <p><span className="text-foreground font-medium">Redundancy</span> via pairwise distance correlation</p>
                  <p><span className="text-foreground font-medium">Stability</span> = IC across walk-forward folds</p>
                </div>
              </div>
            </div>
          </div>
          <div className="quant-card overflow-hidden">
            <h2 className="text-sm font-semibold mb-3">CMI Synergy Matrix</h2>
            {matFeats.length > 0 ? <SynergyHeatmap features={matFeats} matrix={matrix} /> : (
              <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
                <Network className="w-8 h-8 mb-2 opacity-30" />
                <p className="text-xs">Matrix not available</p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
