import axios from "axios";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  headers: { "Content-Type": "application/json" },
  timeout: 30000,
});

apiClient.interceptors.response.use(
  (r) => r,
  (error) => {
    const msg = error.response?.data?.detail || error.message || "Request failed";
    return Promise.reject(new Error(msg));
  }
);

export interface Dataset {
  id: string; name: string; description?: string;
  row_count?: number; asset_count?: number;
  date_range?: { start: string; end: string; trading_days: number };
  columns?: string[]; status: string; is_sample: boolean;
  created_at: string; updated_at: string;
}

export interface Experiment {
  id: string; name: string; description?: string;
  dataset_id: string; target_col: string; target_type: string;
  status: string; current_generation: number; total_generations: number;
  progress: number; error_msg?: string; summary?: Record<string, unknown>;
  seed: number; created_at: string; updated_at: string; completed_at?: string;
}

export interface Subset {
  id: string; experiment_id: string; rank?: number;
  feature_names?: string[]; subset_size?: number;
  relevance_score?: number; redundancy_score?: number;
  synergy_score?: number; stability_score?: number;
  portfolio_score?: number; composite_score?: number;
  pareto_rank?: number; metrics?: Record<string, unknown>; created_at: string;
}

export interface Generation {
  id: string; experiment_id: string; generation_num: number;
  best_fitness?: Record<string, number>; mean_fitness?: Record<string, number>;
  diversity?: number; pareto_front_size?: number; created_at: string;
}

export interface PortfolioResult {
  id: string; method: string; sharpe?: number; sortino?: number;
  max_drawdown?: number; annualized_return?: number; annualized_vol?: number;
  hit_rate?: number; information_ratio?: number; turnover?: number;
  decile_spread?: number; calmar?: number;
  returns_ts?: number[]; cumulative_returns_ts?: number[];
  drawdown_ts?: number[]; dates_ts?: string[]; created_at: string;
}

export interface ExperimentCreateRequest {
  name: string; description?: string; dataset_id: string;
  target_col: string; target_type?: string; population_size?: number;
  n_generations?: number; subset_size_min?: number; subset_size_max?: number;
  objective_weights?: Record<string, number>; run_gp?: boolean; run_ga?: boolean; seed?: number;
}

export const datasetsApi = {
  list: () => apiClient.get<Dataset[]>("/datasets").then(r => r.data),
  get: (id: string) => apiClient.get<Dataset>(`/datasets/${id}`).then(r => r.data),
  createSample: () => apiClient.post<Dataset>("/datasets/sample").then(r => r.data),
  upload: (form: FormData) => apiClient.post<Dataset>("/datasets/upload", form, { headers: { "Content-Type": "multipart/form-data" } }).then(r => r.data),
  preview: (id: string, nRows = 10) => apiClient.get(`/datasets/${id}/preview?n_rows=${nRows}`).then(r => r.data),
  stats: (id: string) => apiClient.get(`/datasets/${id}/stats`).then(r => r.data),
  delete: (id: string) => apiClient.delete(`/datasets/${id}`).then(r => r.data),
};

export const experimentsApi = {
  list: () => apiClient.get<Experiment[]>("/experiments").then(r => r.data),
  get: (id: string) => apiClient.get<Experiment>(`/experiments/${id}`).then(r => r.data),
  run: (data: ExperimentCreateRequest) => apiClient.post<Experiment>("/experiments/run", data).then(r => r.data),
  stop: (id: string) => apiClient.post(`/experiments/${id}/stop`).then(r => r.data),
  pareto: (id: string) => apiClient.get(`/experiments/${id}/pareto`).then(r => r.data),
  generations: (id: string) => apiClient.get<Generation[]>(`/experiments/${id}/generations`).then(r => r.data),
  subsets: (id: string, limit = 20) => apiClient.get<Subset[]>(`/experiments/${id}/subsets?limit=${limit}`).then(r => r.data),
  report: (id: string) => apiClient.get(`/experiments/${id}/report`).then(r => r.data),
};

export const featuresApi = {
  listOperators: () => apiClient.get("/features/operators").then(r => r.data),
  validateExpression: (expression: string) => apiClient.post("/features/expression/validate", { expression }).then(r => r.data),
  generate: (datasetId: string, maxFeatures = 200) => apiClient.post("/features/generate", { dataset_id: datasetId, max_features: maxFeatures }).then(r => r.data),
};

export const portfolioApi = {
  backtest: (data: { subset_id?: string; feature_names?: string[]; dataset_id?: string; target_col?: string; method?: string; n_quantiles?: number }) =>
    apiClient.post<PortfolioResult>("/portfolio/backtest", data).then(r => r.data),
  get: (id: string) => apiClient.get<PortfolioResult>(`/portfolio/${id}`).then(r => r.data),
};

export function createExperimentStream(experimentId: string, onMessage: (data: Record<string, unknown>) => void, onError?: (err: Event) => void): EventSource {
  const url = `${API_BASE}/api/v1/experiments/${experimentId}/stream`;
  const es = new EventSource(url);
  es.onmessage = (event) => { try { onMessage(JSON.parse(event.data)); } catch {} };
  if (onError) es.onerror = onError;
  return es;
}
