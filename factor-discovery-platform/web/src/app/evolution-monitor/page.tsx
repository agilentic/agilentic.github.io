"use client";

import { useState, useEffect, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useSearchParams, useRouter } from "next/navigation";
import { toast } from "sonner";
import { Activity, Play, Square, Loader2, TrendingUp, GitBranch, Layers, Target, ChevronDown, RefreshCw } from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, ScatterChart, Scatter, Legend } from "recharts";
import { experimentsApi, createExperimentStream, Subset, Generation } from "@/lib/api";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { MetricCard } from "@/components/ui/MetricCard";
import { relativeTime } from "@/lib/utils";
import { cn } from "@/lib/utils";

function SubsetRow({ subset, rank }: { subset: Subset; rank: number }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="border border-border rounded-md overflow-hidden">
      <button onClick={() => setExpanded((e) => !e)} className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-secondary transition-colors text-left">
        <span className="text-xs font-mono text-muted-foreground w-5 text-right">#{rank}</span>
        <div className="flex-1 min-w-0 flex items-center gap-2 flex-wrap">
          {(subset.feature_names ?? []).slice(0, 4).map((f) => (
            <span key={f} className="text-xs bg-primary/10 text-primary border border-primary/20 rounded px-1.5 py-0.5 font-mono">{f}</span>
          ))}
          {(subset.feature_names?.length ?? 0) > 4 && (
            <span className="text-xs text-muted-foreground">+{(subset.feature_names?.length ?? 0) - 4}</span>
          )}
        </div>
        <div className="flex items-center gap-3 ml-2 flex-shrink-0">
          <span className="text-xs font-mono text-green-400">IC {((subset.relevance_score ?? 0) * 100).toFixed(1)}%</span>
          <span className="text-xs font-mono text-purple-400">Syn {((subset.synergy_score ?? 0) * 100).toFixed(1)}%</span>
          <ChevronDown className={cn("w-3.5 h-3.5 text-muted-foreground transition-transform", expanded && "rotate-180")} />
        </div>
      </button>
      {expanded && (
        <div className="px-4 pb-3 pt-2 bg-secondary/20 border-t border-border">
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-xs mb-3">
            {[["Relevance", subset.relevance_score, "text-cyan-400"], ["Synergy", subset.synergy_score, "text-purple-400"], ["Redundancy", subset.redundancy_score, "text-red-400"], ["Stability", subset.stability_score, "text-green-400"], ["Portfolio", subset.portfolio_score, "text-yellow-400"], ["Composite", subset.composite_score, "text-foreground"]].map(([l, v, c]) => (
              <div key={String(l)}><p className="text-muted-foreground">{l}</p><p className={cn("font-mono font-semibold", String(c))}>{v != null ? (v as number).toFixed(4) : "—"}</p></div>
            ))}
          </div>
          <div className="flex flex-wrap gap-1">
            {(subset.feature_names ?? []).map((f) => (
              <span key={f} className="text-xs bg-secondary border border-border rounded px-2 py-0.5 font-mono">{f}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function EvolutionMonitorPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const expIdFromUrl = searchParams.get("id");
  const [selectedExpId, setSelectedExpId] = useState<string | null>(expIdFromUrl);
  const streamRef = useRef<EventSource | null>(null);
  const [liveProgress, setLiveProgress] = useState<number | null>(null);
  const [liveGen, setLiveGen] = useState<number | null>(null);

  const { data: experiments = [] } = useQuery({ queryKey: ["experiments"], queryFn: experimentsApi.list, refetchInterval: 5000 });
  const { data: experiment, refetch: refetchExp } = useQuery({ queryKey: ["experiment", selectedExpId], queryFn: () => experimentsApi.get(selectedExpId!), enabled: !!selectedExpId, refetchInterval: (q) => q.state.data?.status === "running" ? 3000 : false });
  const { data: generations = [] } = useQuery({ queryKey: ["generations", selectedExpId], queryFn: () => experimentsApi.generations(selectedExpId!), enabled: !!selectedExpId, refetchInterval: () => { const exp = experiments.find((e) => e.id === selectedExpId); return exp?.status === "running" ? 4000 : false; } });
  const { data: subsets = [] } = useQuery({ queryKey: ["subsets", selectedExpId], queryFn: () => experimentsApi.subsets(selectedExpId!), enabled: !!selectedExpId && experiment?.status === "completed" });
  const { data: paretoData } = useQuery({ queryKey: ["pareto", selectedExpId], queryFn: () => experimentsApi.pareto(selectedExpId!), enabled: !!selectedExpId && experiment?.status === "completed" });

  const stopMutation = useMutation({
    mutationFn: () => experimentsApi.stop(selectedExpId!),
    onSuccess: () => { refetchExp(); queryClient.invalidateQueries({ queryKey: ["experiments"] }); toast.success("Stopped"); },
    onError: (e: Error) => toast.error(e.message),
  });

  useEffect(() => {
    if (!selectedExpId || experiment?.status !== "running") { streamRef.current?.close(); return; }
    streamRef.current?.close();
    const es = createExperimentStream(selectedExpId, (data) => {
      if (data.progress != null) setLiveProgress(data.progress as number);
      if (data.current_generation != null) setLiveGen(data.current_generation as number);
    });
    streamRef.current = es;
    return () => es.close();
  }, [selectedExpId, experiment?.status]);

  const progress = liveProgress ?? experiment?.progress ?? 0;
  const currentGen = liveGen ?? experiment?.current_generation ?? 0;
  const genData = generations.map((g: Generation) => ({ gen: g.generation_num, relevance: g.best_fitness?.relevance ?? 0, synergy: g.best_fitness?.synergy ?? 0, stability: g.best_fitness?.stability ?? 0 }));
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const paretoPoints = ((paretoData as any)?.solutions ?? []).map((s: any) => ({ relevance: s.relevance ?? 0, synergy: s.synergy ?? 0, rank: s.pareto_rank ?? 1 }));

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold flex items-center gap-2"><Activity className="w-6 h-6 text-primary" />Evolution Monitor</h1><p className="text-sm text-muted-foreground mt-1">Real-time NSGA-II progress and Pareto frontier</p></div>
        <div className="flex gap-2">
          {experiment?.status === "running" && (
            <button onClick={() => stopMutation.mutate()} disabled={stopMutation.isPending} className="flex items-center gap-2 bg-red-500/20 text-red-400 border border-red-500/30 px-3 py-1.5 rounded-md text-sm hover:bg-red-500/30 disabled:opacity-60">
              {stopMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Square className="w-4 h-4" />}Stop
            </button>
          )}
          <button onClick={() => router.push("/experiments")} className="flex items-center gap-2 bg-primary text-primary-foreground px-3 py-1.5 rounded-md text-sm font-medium hover:bg-primary/90"><Play className="w-4 h-4" />New Experiment</button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        <div className="quant-card">
          <h2 className="text-sm font-semibold mb-3">Experiments</h2>
          <div className="space-y-1 max-h-96 overflow-y-auto">
            {experiments.length === 0 ? <p className="text-xs text-muted-foreground py-4 text-center">No experiments</p> : experiments.map((exp) => (
              <button key={exp.id} onClick={() => setSelectedExpId(exp.id)} className={cn("w-full text-left px-3 py-2 rounded-md transition-colors", selectedExpId === exp.id ? "bg-primary/10 text-primary" : "hover:bg-secondary")}>
                <p className="text-xs font-medium truncate">{exp.name}</p>
                <div className="flex items-center gap-2 mt-0.5"><StatusBadge status={exp.status} /><span className="text-[10px] text-muted-foreground">{relativeTime(exp.created_at)}</span></div>
              </button>
            ))}
          </div>
        </div>

        <div className="lg:col-span-3 space-y-4">
          {!selectedExpId ? (
            <div className="quant-card flex flex-col items-center justify-center py-20 text-muted-foreground"><GitBranch className="w-10 h-10 mb-3 opacity-30" /><p className="text-sm">Select an experiment</p></div>
          ) : <>
            {experiment && (
              <div className="quant-card">
                <div className="flex items-center justify-between mb-3"><div><p className="text-sm font-semibold">{experiment.name}</p><p className="text-xs text-muted-foreground">{experiment.target_col} · seed {experiment.seed}</p></div><StatusBadge status={experiment.status} size="md" /></div>
                <div className="space-y-1"><div className="flex justify-between text-xs text-muted-foreground"><span>Gen {currentGen}/{experiment.total_generations}</span><span>{Math.round(progress * 100)}%</span></div><div className="h-1.5 bg-secondary rounded-full overflow-hidden"><div className="h-full bg-primary rounded-full transition-all duration-500" style={{ width: `${progress * 100}%` }} /></div></div>
                {experiment.error_msg && <p className="mt-2 text-xs text-red-400">{experiment.error_msg}</p>}
              </div>
            )}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard title="Generation" value={currentGen} icon={RefreshCw} />
              <MetricCard title="Pareto" value={paretoPoints.filter((p: {rank: number}) => p.rank === 1).length || "—"} icon={Target} />
              <MetricCard title="Subsets" value={subsets.length} icon={Layers} />
              <MetricCard title="Best IC" value={generations.length > 0 ? (Math.max(...generations.map((g: Generation) => g.best_fitness?.relevance ?? 0)) * 100).toFixed(1) + "%" : "—"} icon={TrendingUp} />
            </div>
            {genData.length > 0 && (
              <div className="quant-card">
                <h2 className="text-sm font-semibold mb-3">Fitness Over Generations</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={genData} margin={{ top: 5, right: 10, bottom: 5, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(222 30% 18%)" />
                    <XAxis dataKey="gen" tick={{ fontSize: 10, fill: "hsl(215 20% 50%)" }} />
                    <YAxis tick={{ fontSize: 10, fill: "hsl(215 20% 50%)" }} domain={[0, 1]} />
                    <Tooltip contentStyle={{ background: "hsl(222 47% 10%)", border: "1px solid hsl(222 30% 18%)", fontSize: 11 }} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="relevance" stroke="#22d3ee" dot={false} strokeWidth={1.5} />
                    <Line type="monotone" dataKey="synergy" stroke="#a78bfa" dot={false} strokeWidth={1.5} />
                    <Line type="monotone" dataKey="stability" stroke="#34d399" dot={false} strokeWidth={1.5} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
            {paretoPoints.length > 0 && (
              <div className="quant-card">
                <h2 className="text-sm font-semibold mb-3">Pareto Frontier (Relevance vs Synergy)</h2>
                <ResponsiveContainer width="100%" height={200}>
                  <ScatterChart margin={{ top: 5, right: 10, bottom: 5, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(222 30% 18%)" />
                    <XAxis dataKey="relevance" name="Relevance" tick={{ fontSize: 10, fill: "hsl(215 20% 50%)" }} domain={[0, 1]} />
                    <YAxis dataKey="synergy" name="Synergy" tick={{ fontSize: 10, fill: "hsl(215 20% 50%)" }} domain={[0, 1]} />
                    <Tooltip contentStyle={{ background: "hsl(222 47% 10%)", border: "1px solid hsl(222 30% 18%)", fontSize: 11 }} cursor={{ strokeDasharray: "3 3" }} />
                    <Scatter name="Pareto front" data={paretoPoints.filter((p: {rank: number}) => p.rank === 1)} fill="#22d3ee" opacity={0.9} />
                    <Scatter name="Dominated" data={paretoPoints.filter((p: {rank: number}) => p.rank > 1)} fill="hsl(215 20% 40%)" opacity={0.5} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </ScatterChart>
                </ResponsiveContainer>
              </div>
            )}
            {subsets.length > 0 && (
              <div className="quant-card">
                <h2 className="text-sm font-semibold mb-3 flex items-center gap-2"><Layers className="w-4 h-4 text-primary" />Top Subsets</h2>
                <div className="space-y-2">{subsets.slice(0, 10).map((s: Subset, i: number) => <SubsetRow key={s.id} subset={s} rank={i + 1} />)}</div>
              </div>
            )}
            {experiment?.status === "running" && generations.length === 0 && (
              <div className="quant-card flex items-center justify-center py-12 text-muted-foreground gap-3"><Loader2 className="w-5 h-5 animate-spin text-primary" /><p className="text-sm">Initializing evolution...</p></div>
            )}
          </>}
        </div>
      </div>
    </div>
  );
}
