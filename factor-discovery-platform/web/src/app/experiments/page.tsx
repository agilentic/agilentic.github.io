"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { FileText, Play, Square, Loader2, ChevronDown, ChevronRight, BarChart3, AlertCircle } from "lucide-react";
import { experimentsApi, datasetsApi, ExperimentCreateRequest, Experiment } from "@/lib/api";
import { useAppStore } from "@/store";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { relativeTime } from "@/lib/utils";
import { cn } from "@/lib/utils";

const INPUT = "w-full bg-secondary border border-border rounded px-3 py-1.5 text-sm focus:outline-none focus:border-primary/60 transition-colors";

function ExpRow({ exp, onStop, stopping }: { exp: Experiment; onStop: () => void; stopping: boolean }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  return (
    <div className="border border-border rounded-md overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 hover:bg-secondary/50 cursor-pointer transition-colors" onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">{exp.name}</p>
          <p className="text-xs text-muted-foreground">{relativeTime(exp.created_at)} · {exp.target_col} · gen {exp.current_generation}/{exp.total_generations}</p>
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          {exp.status === "running" && <span className="text-xs text-muted-foreground font-mono">{Math.round(exp.progress * 100)}%</span>}
          <StatusBadge status={exp.status} />
          <div onClick={(e) => e.stopPropagation()} className="flex items-center gap-1">
            {exp.status === "running" && (
              <button onClick={onStop} disabled={stopping} className="p-1.5 rounded text-red-400 hover:bg-red-500/10 disabled:opacity-60 transition-colors">
                {stopping ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Square className="w-3.5 h-3.5" />}
              </button>
            )}
            {exp.status === "completed" && (
              <button onClick={() => router.push(`/evolution-monitor?id=${exp.id}`)} className="p-1.5 rounded text-primary hover:bg-primary/10 transition-colors">
                <BarChart3 className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
      {open && (
        <div className="px-4 pb-4 pt-2 bg-secondary/20 border-t border-border">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs">
            <div><p className="text-muted-foreground">ID</p><p className="font-mono text-[10px] break-all">{exp.id}</p></div>
            <div><p className="text-muted-foreground">Target</p><p className="font-mono">{exp.target_col}</p></div>
            <div><p className="text-muted-foreground">Type</p><p className="font-mono">{exp.target_type}</p></div>
            <div><p className="text-muted-foreground">Seed</p><p className="font-mono">{exp.seed}</p></div>
          </div>
          {exp.error_msg && <div className="mt-3 flex items-start gap-2 text-red-400 text-xs"><AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />{exp.error_msg}</div>}
          {exp.status === "completed" && exp.summary && (
            <div className="mt-3">
              <p className="text-xs font-medium mb-1.5">Summary</p>
              <div className="grid grid-cols-3 gap-3 text-xs">
                {Object.entries(exp.summary as Record<string, unknown>).slice(0, 6).map(([k, v]) => (
                  <div key={k}><p className="text-muted-foreground">{k.replace(/_/g, " ")}</p><p className="font-mono font-medium">{typeof v === "number" ? v.toFixed(4) : String(v)}</p></div>
                ))}
              </div>
            </div>
          )}
          <div className="mt-3 flex gap-2">
            {exp.status === "completed" && (
              <>
                <button onClick={() => router.push(`/evolution-monitor?id=${exp.id}`)} className="text-xs bg-primary/10 text-primary border border-primary/20 px-3 py-1.5 rounded hover:bg-primary/20 transition-colors">View Evolution</button>
                <button onClick={() => router.push("/portfolio-lab")} className="text-xs bg-secondary border border-border px-3 py-1.5 rounded hover:border-primary/40 transition-colors">Backtest Portfolio</button>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ExperimentsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { activeDataset } = useAppStore();
  const [showForm, setShowForm] = useState(false);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [form, setForm] = useState({
    name: "", description: "", dataset_id: activeDataset ?? "", target_col: "target_return_1d",
    target_type: "return", population_size: 50, n_generations: 20,
    subset_size_min: 3, subset_size_max: 10, run_gp: true, run_ga: true, seed: 42,
  });

  const { data: experiments = [], isLoading } = useQuery({ queryKey: ["experiments"], queryFn: experimentsApi.list, refetchInterval: 5000 });
  const { data: datasets = [] } = useQuery({ queryKey: ["datasets"], queryFn: datasetsApi.list });
  const runMutation = useMutation({
    mutationFn: (d: ExperimentCreateRequest) => experimentsApi.run(d),
    onSuccess: (exp) => { queryClient.invalidateQueries({ queryKey: ["experiments"] }); setShowForm(false); toast.success("Experiment started"); router.push(`/evolution-monitor?id=${exp.id}`); },
    onError: (e: Error) => toast.error(e.message),
  });
  const stopMutation = useMutation({
    mutationFn: (id: string) => experimentsApi.stop(id),
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ["experiments"] }); setStoppingId(null); toast.success("Stopped"); },
    onError: (e: Error) => { setStoppingId(null); toast.error(e.message); },
  });

  const f = (key: string, value: unknown) => setForm((prev) => ({ ...prev, [key]: value }));
  const running = experiments.filter((e) => e.status === "running");
  const completed = experiments.filter((e) => e.status === "completed");
  const failed = experiments.filter((e) => e.status === "failed" || e.status === "stopped");

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold flex items-center gap-2"><FileText className="w-6 h-6 text-primary" />Experiments</h1><p className="text-sm text-muted-foreground mt-1">Launch and manage NSGA-II + GP optimization runs</p></div>
        <button onClick={() => setShowForm((s) => !s)} className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium hover:bg-primary/90 transition-colors"><Play className="w-4 h-4" />New Experiment</button>
      </div>

      {showForm && (
        <div className="quant-card border-primary/30">
          <h2 className="text-sm font-semibold mb-4">Configure New Experiment</h2>
          <form onSubmit={(e) => { e.preventDefault(); if (!form.name.trim()) return toast.error("Name required"); if (!form.dataset_id) return toast.error("Select a dataset"); runMutation.mutate({ name: form.name, description: form.description || undefined, dataset_id: form.dataset_id, target_col: form.target_col, target_type: form.target_type, population_size: form.population_size, n_generations: form.n_generations, subset_size_min: form.subset_size_min, subset_size_max: form.subset_size_max, run_gp: form.run_gp, run_ga: form.run_ga, seed: form.seed }); }} className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div><label className="block text-xs font-medium mb-1">Name *</label><input value={form.name} onChange={(e) => f("name", e.target.value)} placeholder="e.g. NSGA-II run v1" className={INPUT} required /></div>
              <div><label className="block text-xs font-medium mb-1">Dataset</label><select value={form.dataset_id} onChange={(e) => f("dataset_id", e.target.value)} className={INPUT} required><option value="">Select...</option>{datasets.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select></div>
              <div><label className="block text-xs font-medium mb-1">Target Column</label><input value={form.target_col} onChange={(e) => f("target_col", e.target.value)} className={INPUT} /></div>
              <div><label className="block text-xs font-medium mb-1">Target Type</label><select value={form.target_type} onChange={(e) => f("target_type", e.target.value)} className={INPUT}>{["return","rank","binary","decile"].map((t) => <option key={t} value={t}>{t}</option>)}</select></div>
              <div><label className="block text-xs font-medium mb-1">Population ({form.population_size})</label><input type="range" min={20} max={200} step={10} value={form.population_size} onChange={(e) => f("population_size", Number(e.target.value))} className="w-full accent-primary mt-1" /></div>
              <div><label className="block text-xs font-medium mb-1">Generations ({form.n_generations})</label><input type="range" min={5} max={100} step={5} value={form.n_generations} onChange={(e) => f("n_generations", Number(e.target.value))} className="w-full accent-primary mt-1" /></div>
              <div><label className="block text-xs font-medium mb-1">Min Subset Size</label><input type="number" min={1} max={20} value={form.subset_size_min} onChange={(e) => f("subset_size_min", Number(e.target.value))} className={INPUT} /></div>
              <div><label className="block text-xs font-medium mb-1">Max Subset Size</label><input type="number" min={1} max={50} value={form.subset_size_max} onChange={(e) => f("subset_size_max", Number(e.target.value))} className={INPUT} /></div>
            </div>
            <div className="flex items-center gap-6">
              <label className="flex items-center gap-2 text-sm cursor-pointer"><input type="checkbox" checked={form.run_gp} onChange={(e) => f("run_gp", e.target.checked)} className="accent-primary" />Run GP expression search</label>
              <label className="flex items-center gap-2 text-sm cursor-pointer"><input type="checkbox" checked={form.run_ga} onChange={(e) => f("run_ga", e.target.checked)} className="accent-primary" />Run GA (NSGA-II)</label>
            </div>
            <div className="flex gap-2">
              <button type="submit" disabled={runMutation.isPending} className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded text-sm font-medium hover:bg-primary/90 disabled:opacity-60 transition-colors">{runMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}Launch Experiment</button>
              <button type="button" onClick={() => setShowForm(false)} className="px-4 py-2 rounded text-sm border border-border hover:bg-secondary transition-colors">Cancel</button>
            </div>
          </form>
        </div>
      )}

      <div className="grid grid-cols-3 gap-4">
        {[["Running", running.length, "text-blue-400"], ["Completed", completed.length, "text-green-400"], ["Failed/Stopped", failed.length, "text-red-400"]].map(([l, c, color]) => (
          <div key={String(l)} className="quant-card py-3 text-center"><p className={cn("text-2xl font-mono font-bold", String(color))}>{c}</p><p className="text-xs text-muted-foreground">{l}</p></div>
        ))}
      </div>

      <div>
        <h2 className="text-sm font-semibold mb-3">All Experiments ({experiments.length})</h2>
        {isLoading ? [1, 2, 3].map((i) => <div key={i} className="h-14 bg-muted rounded animate-pulse mb-2" />) : experiments.length === 0 ? (
          <div className="quant-card text-center py-12 text-muted-foreground"><FileText className="w-8 h-8 mx-auto mb-2 opacity-30" /><p className="text-sm">No experiments yet.</p><button onClick={() => setShowForm(true)} className="mt-3 text-primary text-xs hover:underline">Run your first experiment →</button></div>
        ) : (
          <div className="space-y-2">
            {experiments.map((exp) => <ExpRow key={exp.id} exp={exp} stopping={stoppingId === exp.id} onStop={() => { setStoppingId(exp.id); stopMutation.mutate(exp.id); }} />)}
          </div>
        )}
      </div>
    </div>
  );
}
