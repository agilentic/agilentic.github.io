from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Any


class DatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None = None
    row_count: int | None = None
    asset_count: int | None = None
    date_range: dict | None = None
    columns: list | None = None
    status: str
    is_sample: bool
    created_at: datetime
    updated_at: datetime


class ExperimentCreate(BaseModel):
    name: str
    description: str | None = None
    dataset_id: str
    target_col: str
    target_type: str = "return"
    population_size: int = 50
    n_generations: int = 20
    subset_size_min: int = 3
    subset_size_max: int = 10
    objective_weights: dict[str, float] | None = None
    run_gp: bool = True
    run_ga: bool = True
    seed: int = 42


class ExperimentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    description: str | None = None
    dataset_id: str
    target_col: str
    target_type: str
    status: str
    current_generation: int
    total_generations: int
    progress: float
    error_msg: str | None = None
    summary: dict | None = None
    seed: int
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class SubsetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    experiment_id: str
    rank: int | None = None
    feature_names: list[str] | None = None
    subset_size: int | None = None
    relevance_score: float | None = None
    redundancy_score: float | None = None
    synergy_score: float | None = None
    stability_score: float | None = None
    portfolio_score: float | None = None
    composite_score: float | None = None
    pareto_rank: int | None = None
    metrics: dict | None = None
    created_at: datetime


class GenerationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    experiment_id: str
    generation_num: int
    best_fitness: dict | None = None
    mean_fitness: dict | None = None
    diversity: float | None = None
    pareto_front_size: int | None = None
    created_at: datetime


class PortfolioResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    method: str
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown: float | None = None
    annualized_return: float | None = None
    annualized_vol: float | None = None
    hit_rate: float | None = None
    information_ratio: float | None = None
    turnover: float | None = None
    decile_spread: float | None = None
    calmar: float | None = None
    returns_ts: list[float] | None = None
    cumulative_returns_ts: list[float] | None = None
    drawdown_ts: list[float] | None = None
    dates_ts: list[str] | None = None
    created_at: datetime


class BacktestRequest(BaseModel):
    subset_id: str | None = None
    feature_names: list[str] | None = None
    dataset_id: str | None = None
    target_col: str | None = None
    method: str = "ic"
    n_quantiles: int = 10
