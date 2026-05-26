import uuid
from datetime import datetime
from sqlalchemy import String, Float, Integer, Boolean, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from api.app.core.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(String(512))
    row_count: Mapped[int | None] = mapped_column(Integer)
    asset_count: Mapped[int | None] = mapped_column(Integer)
    date_range: Mapped[dict | None] = mapped_column(JSON)
    columns: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50), default="ready")
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    experiments: Mapped[list["Experiment"]] = relationship("Experiment", back_populates="dataset")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    dataset_id: Mapped[str] = mapped_column(String(36), ForeignKey("datasets.id"), nullable=False)
    target_col: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), default="return")
    config: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    current_generation: Mapped[int] = mapped_column(Integer, default=0)
    total_generations: Mapped[int] = mapped_column(Integer, default=20)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    error_msg: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSON)
    seed: Mapped[int] = mapped_column(Integer, default=42)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="experiments")
    subsets: Mapped[list["Subset"]] = relationship("Subset", back_populates="experiment")
    generations: Mapped[list["GenerationRecord"]] = relationship("GenerationRecord", back_populates="experiment")


class Subset(Base):
    __tablename__ = "subsets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    experiment_id: Mapped[str] = mapped_column(String(36), ForeignKey("experiments.id"), nullable=False)
    rank: Mapped[int | None] = mapped_column(Integer)
    feature_names: Mapped[list | None] = mapped_column(JSON)
    subset_size: Mapped[int | None] = mapped_column(Integer)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    redundancy_score: Mapped[float | None] = mapped_column(Float)
    synergy_score: Mapped[float | None] = mapped_column(Float)
    stability_score: Mapped[float | None] = mapped_column(Float)
    portfolio_score: Mapped[float | None] = mapped_column(Float)
    composite_score: Mapped[float | None] = mapped_column(Float)
    pareto_rank: Mapped[int | None] = mapped_column(Integer)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    explanation: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    experiment: Mapped["Experiment"] = relationship("Experiment", back_populates="subsets")


class GenerationRecord(Base):
    __tablename__ = "generation_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    experiment_id: Mapped[str] = mapped_column(String(36), ForeignKey("experiments.id"), nullable=False)
    generation_num: Mapped[int] = mapped_column(Integer, nullable=False)
    best_fitness: Mapped[dict | None] = mapped_column(JSON)
    mean_fitness: Mapped[dict | None] = mapped_column(JSON)
    diversity: Mapped[float | None] = mapped_column(Float)
    pareto_front_size: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    experiment: Mapped["Experiment"] = relationship("Experiment", back_populates="generations")


class PortfolioResult(Base):
    __tablename__ = "portfolio_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    experiment_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("experiments.id"))
    subset_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("subsets.id"))
    method: Mapped[str] = mapped_column(String(50), default="ic")
    sharpe: Mapped[float | None] = mapped_column(Float)
    sortino: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    annualized_return: Mapped[float | None] = mapped_column(Float)
    annualized_vol: Mapped[float | None] = mapped_column(Float)
    hit_rate: Mapped[float | None] = mapped_column(Float)
    information_ratio: Mapped[float | None] = mapped_column(Float)
    turnover: Mapped[float | None] = mapped_column(Float)
    decile_spread: Mapped[float | None] = mapped_column(Float)
    calmar: Mapped[float | None] = mapped_column(Float)
    returns_ts: Mapped[list | None] = mapped_column(JSON)
    cumulative_returns_ts: Mapped[list | None] = mapped_column(JSON)
    drawdown_ts: Mapped[list | None] = mapped_column(JSON)
    dates_ts: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
