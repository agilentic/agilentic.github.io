"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { Database, Upload, Trash2, Eye, BarChart2, CheckCircle, AlertCircle, Loader2, Plus, Calendar, TrendingUp } from "lucide-react";
import { datasetsApi, Dataset } from "@/lib/api";
import { useAppStore } from "@/store";
import { formatNumber, relativeTime } from "@/lib/utils";
import { cn } from "@/lib/utils";

function DatasetCard({ dataset, active, onSelect, onDelete }: { dataset: Dataset; active: boolean; onSelect: () => void; onDelete: () => void }) {
  return (
    <div className={cn("quant-card cursor-pointer transition-all border", active ? "border-primary/60 bg-primary/5" : "border-border hover:border-primary/30")} onClick={onSelect}>
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <Database className="w-4 h-4 text-primary flex-shrink-0" />
          <div>
            <p className="text-sm font-medium leading-tight">{dataset.name}</p>
            <p className="text-xs text-muted-foreground">{relativeTime(dataset.created_at)}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {dataset.is_sample && <span className="text-[10px] bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded px-1.5 py-0.5">SAMPLE</span>}
          <button onClick={e => { e.stopPropagation(); onDelete(); }} className="p-1 text-muted-foreground hover:text-red-400 transition-colors">
            <Trash2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
        <div><p className="text-muted-foreground">Assets</p><p className="font-mono font-bold">{dataset.asset_count ?? "—"}</p></div>
        <div><p className="text-muted-foreground">Rows</p><p className="font-mono font-bold">{dataset.row_count ? formatNumber(dataset.row_count) : "—"}</p></div>
        <div><p className="text-muted-foreground">Days</p><p className="font-mono font-bold">{dataset.date_range?.trading_days ?? "—"}</p></div>
      </div>
    </div>
  );
}

export default function DataStudioPage() {
  const queryClient = useQueryClient();
  const { activeDataset, setActiveDataset } = useAppStore();
  const [previewId, setPreviewId] = useState<string | null>(null);

  const { data: datasets = [], isLoading } = useQuery({ queryKey: ["datasets"], queryFn: datasetsApi.list });
  const { data: preview, isLoading: previewLoading } = useQuery({ queryKey: ["preview", previewId], queryFn: () => datasetsApi.preview(previewId!, 10), enabled: !!previewId });
  const { data: stats, isLoading: statsLoading } = useQuery({ queryKey: ["stats", previewId], queryFn: () => datasetsApi.stats(previewId!), enabled: !!previewId });

  const sampleMutation = useMutation({ mutationFn: datasetsApi.createSample, onSuccess: ds => { queryClient.invalidateQueries({ queryKey: ["datasets"] }); setActiveDataset(ds.id); setPreviewId(ds.id); toast.success("Sample dataset loaded"); }, onError: (e: Error) => toast.error(e.message) });
  const uploadMutation = useMutation({ mutationFn: (form: FormData) => datasetsApi.upload(form), onSuccess: ds => { queryClient.invalidateQueries({ queryKey: ["datasets"] }); setActiveDataset(ds.id); setPreviewId(ds.id); toast.success("Uploaded"); }, onError: (e: Error) => toast.error(e.message) });
  const deleteMutation = useMutation({ mutationFn: datasetsApi.delete, onSuccess: (_, id) => { queryClient.invalidateQueries({ queryKey: ["datasets"] }); if (activeDataset === id) setActiveDataset(null); if (previewId === id) setPreviewId(null); toast.success("Deleted"); }, onError: (e: Error) => toast.error(e.message) });

  const onDrop = useCallback((files: File[]) => { const f = files[0]; if (!f) return; const form = new FormData(); form.append("file", f); form.append("name", f.name.replace(/\.[^.]+$/, "")); uploadMutation.mutate(form); }, [uploadMutation]);
  const { getRootProps, getInputProps, isDragActive } = useDropzone({ onDrop, accept: { "text/csv": [".csv"], "application/octet-stream": [".parquet"] }, maxFiles: 1 });

  const selected = datasets.find(d => d.id === previewId);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold flex items-center gap-2"><Database className="w-6 h-6 text-primary" />Data Studio</h1><p className="text-sm text-muted-foreground mt-1">Upload and manage datasets</p></div>
        <button onClick={() => sampleMutation.mutate()} disabled={sampleMutation.isPending} className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium hover:bg-primary/90 disabled:opacity-60 transition-colors">
          {sampleMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
          Load Sample Data
        </button>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="space-y-4">
          <div {...getRootProps()} className={cn("quant-card border-2 border-dashed cursor-pointer transition-colors text-center py-8", isDragActive ? "border-primary bg-primary/5" : "border-border hover:border-primary/40", uploadMutation.isPending && "opacity-60 pointer-events-none")}>
            <input {...getInputProps()} />
            {uploadMutation.isPending ? <Loader2 className="w-8 h-8 mx-auto mb-2 animate-spin text-primary" /> : <Upload className="w-8 h-8 mx-auto mb-2 text-muted-foreground" />}
            <p className="text-sm font-medium">{isDragActive ? "Drop file here" : "Upload CSV or Parquet"}</p>
            <p className="text-xs text-muted-foreground mt-1">Panel data with date + ticker columns</p>
          </div>
          <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Datasets ({datasets.length})</h2>
          {isLoading ? [1,2].map(i => <div key={i} className="h-20 bg-muted rounded animate-pulse" />) : datasets.length === 0 ? <div className="quant-card text-center py-6 text-muted-foreground text-sm">No datasets yet.</div> : datasets.map(ds => <DatasetCard key={ds.id} dataset={ds} active={previewId === ds.id} onSelect={() => { setPreviewId(ds.id); setActiveDataset(ds.id); }} onDelete={() => deleteMutation.mutate(ds.id)} />)}
        </div>
        <div className="lg:col-span-2 space-y-4">
          {!previewId ? <div className="quant-card flex flex-col items-center justify-center py-20 text-muted-foreground"><Eye className="w-10 h-10 mb-3 opacity-30" /><p className="text-sm">Select a dataset to preview</p></div> : <>
            {selected && (
              <div className="quant-card">
                <div className="flex items-center gap-2 mb-3"><CheckCircle className="w-4 h-4 text-green-400" /><h2 className="text-sm font-semibold">{selected.name}</h2>{activeDataset === selected.id && <span className="text-[10px] bg-green-500/20 text-green-400 border border-green-500/30 rounded px-1.5 py-0.5">ACTIVE</span>}</div>
                <div className="grid grid-cols-4 gap-4 text-xs">
                  {[["Assets", selected.asset_count ?? "—"], ["Rows", selected.row_count ? formatNumber(selected.row_count) : "—"], ["Days", selected.date_range?.trading_days ?? "—"], ["Cols", selected.columns?.length ?? "—"]].map(([l, v]) => <div key={String(l)}><p className="text-muted-foreground">{l}</p><p className="font-mono font-bold text-base">{v}</p></div>)}
                </div>
                {selected.date_range && <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1"><Calendar className="w-3 h-3" />{selected.date_range.start} → {selected.date_range.end}</p>}
              </div>
            )}
            <div className="quant-card">
              <h2 className="text-sm font-semibold mb-3 flex items-center gap-2"><Eye className="w-4 h-4 text-primary" />Preview (first 10 rows)</h2>
              {previewLoading ? <div className="h-32 bg-muted rounded animate-pulse" /> : preview?.rows?.length > 0 ? (
                <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr className="border-b border-border">{preview.columns.map((c: string) => <th key={c} className="text-left py-2 px-3 font-medium text-muted-foreground uppercase tracking-wide whitespace-nowrap">{c}</th>)}</tr></thead><tbody>{preview.rows.slice(0,10).map((row: Record<string,unknown>, i: number) => <tr key={i} className="border-b border-border/50 hover:bg-secondary/50">{preview.columns.map((c: string) => <td key={c} className="py-1.5 px-3 font-mono whitespace-nowrap">{String(row[c] ?? "—")}</td>)}</tr>)}</tbody></table></div>
              ) : <p className="text-sm text-muted-foreground text-center py-4">No preview available</p>}
            </div>
            {selected?.columns && (
              <div className="quant-card">
                <h2 className="text-sm font-semibold mb-3 flex items-center gap-2"><TrendingUp className="w-4 h-4 text-primary" />Columns</h2>
                <div className="flex flex-wrap gap-1.5">{selected.columns.map(col => <span key={col} className="text-xs bg-secondary border border-border rounded px-2 py-1 font-mono">{col}</span>)}</div>
              </div>
            )}
          </>}
        </div>
      </div>
    </div>
  );
}
