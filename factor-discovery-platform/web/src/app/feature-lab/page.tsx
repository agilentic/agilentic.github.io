"use client";

import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { toast } from "sonner";
import { FlaskConical, Search, CheckCircle, XCircle, Loader2, ChevronDown, ChevronRight, Code2, BookOpen, Sparkles } from "lucide-react";
import { featuresApi } from "@/lib/api";
import { useAppStore } from "@/store";
import { cn } from "@/lib/utils";

interface Operator { name: string; signature: string; description: string; category: string; example?: string; }

const EXAMPLES = [
  { label: "RSI(14)", expr: "rsi(close, 14)" },
  { label: "Rolling Z-score", expr: "rolling_zscore(close, 20)" },
  { label: "Momentum", expr: "pct_change(close, 20) / (rolling_std(close, 20) + 1e-8)" },
  { label: "Mean-rev signal", expr: "zscore_normalize(close - rolling_mean(close, 60))" },
];

function CategorySection({ cat, ops, onSelectOp }: { cat: string; ops: Operator[]; onSelectOp: (op: Operator) => void }) {
  const [open, setOpen] = useState(true);
  return (
    <div>
      <button onClick={() => setOpen(o => !o)} className="w-full flex items-center gap-2 px-2 py-1.5 text-xs font-semibold text-muted-foreground uppercase tracking-wider hover:text-foreground">
        {open ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}{cat} ({ops.length})
      </button>
      {open && ops.map(op => (
        <button key={op.name} onClick={() => onSelectOp(op)} className="w-full text-left flex items-start gap-2 px-3 py-1.5 rounded hover:bg-secondary">
          <Code2 className="w-3.5 h-3.5 text-muted-foreground mt-0.5 flex-shrink-0" />
          <div><p className="text-xs font-mono font-medium text-primary">{op.name}</p><p className="text-xs text-muted-foreground truncate">{op.description}</p></div>
        </button>
      ))}
    </div>
  );
}

export default function FeatureLabPage() {
  const { activeDataset } = useAppStore();
  const [expression, setExpression] = useState("");
  const [search, setSearch] = useState("");
  const [selectedOp, setSelectedOp] = useState<Operator | null>(null);
  const [valResult, setValResult] = useState<{ valid: boolean; error?: string; complexity?: number; depth?: number } | null>(null);

  const { data: catalog, isLoading } = useQuery({ queryKey: ["operators"], queryFn: featuresApi.listOperators });
  const validateMutation = useMutation({ mutationFn: (expr: string) => featuresApi.validateExpression(expr), onSuccess: setValResult, onError: (e: Error) => toast.error(e.message) });
  const generateMutation = useMutation({ mutationFn: () => { if (!activeDataset) throw new Error("No dataset"); return featuresApi.generate(activeDataset); }, onSuccess: (d) => toast.success(`Generated ${d.count ?? "?"} features`), onError: (e: Error) => toast.error(e.message) });

  const filteredCats = catalog ? Object.fromEntries(Object.entries(catalog.categories as Record<string, Operator[]>).map(([cat, ops]) => [cat, ops.filter(op => !search || op.name.toLowerCase().includes(search.toLowerCase()))]).filter(([, ops]) => ops.length > 0)) : {};

  const handleSelectOp = (op: Operator) => {
    setExpression(e => e ? `${e.trimEnd()}\n${op.name}(...)` : `${op.name}(...)`);
    setSelectedOp(op);
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div><h1 className="text-2xl font-bold flex items-center gap-2"><FlaskConical className="w-6 h-6 text-primary" />Feature Lab</h1><p className="text-sm text-muted-foreground mt-1">Browse operators, compose DSL expressions</p></div>
        <button onClick={() => generateMutation.mutate()} disabled={!activeDataset || generateMutation.isPending} className="flex items-center gap-2 bg-primary text-primary-foreground px-4 py-2 rounded-md text-sm font-medium hover:bg-primary/90 disabled:opacity-60 transition-colors">
          {generateMutation.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}
          Generate All Features
        </button>
      </div>
      {!activeDataset && <div className="quant-card border-yellow-500/30 bg-yellow-500/5 text-yellow-400 text-sm flex items-center gap-2 px-4 py-3"><BookOpen className="w-4 h-4 flex-shrink-0" />No dataset selected — go to Data Studio first.</div>}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="quant-card flex flex-col max-h-[75vh]">
          <h2 className="text-sm font-semibold mb-2 flex items-center gap-2"><BookOpen className="w-4 h-4 text-primary" />Operator Library {catalog && <span className="text-xs text-muted-foreground font-normal">({catalog.total})</span>}</h2>
          <div className="relative mb-2"><Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" /><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search..." className="w-full bg-secondary border border-border rounded px-3 py-1.5 pl-8 text-xs focus:outline-none focus:border-primary/60" /></div>
          <div className="flex-1 overflow-y-auto space-y-1">
            {isLoading ? [1,2,3,4].map(i => <div key={i} className="h-6 bg-muted rounded animate-pulse" />) : Object.entries(filteredCats).map(([cat, ops]) => (
              <CategorySection key={cat} cat={cat} ops={ops as Operator[]} onSelectOp={handleSelectOp} />
            ))}
          </div>
        </div>
        <div className="lg:col-span-2 space-y-4">
          <div className="quant-card">
            <h2 className="text-sm font-semibold mb-3 flex items-center gap-2"><Code2 className="w-4 h-4 text-primary" />Expression Editor</h2>
            <textarea value={expression} onChange={e => { setExpression(e.target.value); setValResult(null); }} placeholder="Enter a factor DSL expression..." rows={5} className="w-full bg-secondary border border-border rounded px-3 py-2 text-sm font-mono focus:outline-none focus:border-primary/60 resize-none" />
            <div className="flex gap-2 mt-2">
              <button onClick={() => expression.trim() && validateMutation.mutate(expression.trim())} disabled={!expression.trim() || validateMutation.isPending} className="flex items-center gap-2 bg-primary text-primary-foreground px-3 py-1.5 rounded text-xs font-medium hover:bg-primary/90 disabled:opacity-60">
                {validateMutation.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle className="w-3 h-3" />}Validate
              </button>
              <button onClick={() => { setExpression(""); setValResult(null); }} className="text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 rounded hover:bg-secondary">Clear</button>
            </div>
            {valResult && (
              <div className={cn("mt-3 flex items-start gap-2 px-3 py-2 rounded text-xs border", valResult.valid ? "bg-green-500/10 border-green-500/30 text-green-400" : "bg-red-500/10 border-red-500/30 text-red-400")}>
                {valResult.valid ? <CheckCircle className="w-3.5 h-3.5 mt-0.5" /> : <XCircle className="w-3.5 h-3.5 mt-0.5" />}
                {valResult.valid ? `Valid · complexity=${valResult.complexity} · depth=${valResult.depth}` : valResult.error}
              </div>
            )}
          </div>
          <div className="quant-card">
            <h2 className="text-sm font-semibold mb-3">Examples</h2>
            <div className="grid grid-cols-2 gap-2">
              {EXAMPLES.map(({ label, expr }) => (
                <button key={label} onClick={() => { setExpression(expr); setValResult(null); }} className="text-left px-3 py-2 rounded border border-border hover:border-primary/40 hover:bg-secondary transition-colors">
                  <p className="text-xs font-medium">{label}</p>
                  <p className="text-xs font-mono text-muted-foreground truncate">{expr}</p>
                </button>
              ))}
            </div>
          </div>
          {selectedOp && (
            <div className="quant-card border-primary/30">
              <h2 className="text-sm font-semibold mb-2 flex items-center gap-2"><Code2 className="w-4 h-4 text-primary" />{selectedOp.name} <span className="text-xs font-mono text-muted-foreground font-normal">{selectedOp.signature}</span></h2>
              <p className="text-sm text-muted-foreground">{selectedOp.description}</p>
              <p className="text-xs text-muted-foreground mt-2">Category: <span className="text-foreground">{selectedOp.category}</span></p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
