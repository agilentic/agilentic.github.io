# Factor Discovery Platform

A production-grade, end-to-end system for autonomous discovery, evaluation, and optimization of quantitative alpha factors using multi-objective evolutionary algorithms and genetic programming.

## Architecture

```
factor-discovery-platform/
├── api/                  # FastAPI backend
│   ├── app/
│   │   ├── core/         # Config, database, Redis client
│   │   ├── models/       # SQLAlchemy ORM models
│   │   ├── schemas/      # Pydantic v2 schemas
│   │   └── api/routers/  # REST endpoints
│   └── main.py           # FastAPI app entry point
├── engine/               # Computation engine
│   ├── agents/           # DataAgent, Orchestrator (9-phase pipeline)
│   ├── factors/          # Feature factory (120+ features), GP engine, operators
│   ├── metrics/          # Relevance, Redundancy, Synergy agents
│   ├── optimization/     # NSGA-II GA optimizer (SubsetOptimizer)
│   ├── portfolio/        # PortfolioAgent (IC-weighted, long-short backtest)
│   ├── utils/            # Math utils (distance correlation, CMI, IC)
│   └── validation/       # Walk-forward validator with gap/embargo
├── workers/              # Celery task workers
│   └── tasks/            # experiment_tasks.py
├── web/                  # Next.js 15 frontend
│   └── src/
│       ├── app/          # 7 pages: dashboard, data-studio, feature-lab,
│       │                 #   evolution-monitor, synergy-explorer,
│       │                 #   portfolio-lab, experiments
│       ├── components/   # AppLayout, MetricCard, StatusBadge
│       ├── lib/          # API client, utils
│       └── store/        # Zustand global state
├── infra/                # Docker Compose, Dockerfiles
└── tests/                # Pytest unit tests
```

## Quick Start

### One-command startup (Docker)

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

Services will be available at:
- **Frontend**: http://localhost:3000
- **API**: http://localhost:8000
- **API docs**: http://localhost:8000/docs

### Local development

**Backend:**
```bash
# Install dependencies
pip install -r api/requirements.txt

# Set environment variables
export DATABASE_URL=postgresql+asyncpg://factor:factor@localhost:5432/factordb
export REDIS_URL=redis://localhost:6379/0

# Start API
cd factor-discovery-platform
PYTHONPATH=. uvicorn api.main:app --reload --port 8000

# Start Celery worker (separate terminal)
PYTHONPATH=. celery -A workers.celery_app worker -Q experiments -l info
```

**Frontend:**
```bash
cd web
npm install
npm run dev
```

## Key Concepts

### NSGA-II Multi-Objective Optimization

The `SubsetOptimizer` evolves binary chromosomes over the feature universe with 6 fitness objectives:

| Objective | Description | Weight |
|-----------|-------------|--------|
| Relevance | Mean Spearman IC × ICIR × distance correlation | +1 |
| Synergy | Conditional MI gain I(f; y \| S) | +1 |
| Redundancy | Pairwise distance correlation | −1 |
| Stability | IC consistency across walk-forward folds | +1 |
| Portfolio | Long-short Sharpe from IC-weighted signal | +1 |
| Complexity | Subset size penalty | −0.1 |

### Nonlinear Synergy Scoring

Unlike simple correlation filtering, synergy is measured via:
- **Conditional Mutual Information (CMI)**: `I(f; y | S)` — how much information `f` adds given current subset
- **Incremental IC**: `IC(S + f) − IC(S)` — direct improvement in cross-sectional IC
- Composite: `0.5 × CMI + 0.5 × ΔIC`

### Walk-Forward Validation

`WalkForwardValidator` enforces strict time ordering with a `gap` embargo between train and test windows to prevent data leakage. Stability score measures IC sign consistency, coefficient of variation, and mean/std ratio across folds.

### Distance Correlation

Captures nonlinear dependence (Székely et al. 2007) in O(n²) time. Used in redundancy matrix and relevance scoring. Invariant to monotone transformations.

## Running Tests

```bash
cd factor-discovery-platform
PYTHONPATH=. pytest tests/ -v
```

## API Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/datasets/` | GET | List all datasets |
| `/api/v1/datasets/sample` | POST | Generate synthetic sample dataset |
| `/api/v1/datasets/upload` | POST | Upload CSV/Parquet |
| `/api/v1/datasets/{id}/preview` | GET | Row preview |
| `/api/v1/datasets/{id}/stats` | GET | Column statistics |
| `/api/v1/experiments/` | GET | List experiments |
| `/api/v1/experiments/run` | POST | Launch experiment |
| `/api/v1/experiments/{id}/stream` | GET | SSE live progress |
| `/api/v1/experiments/{id}/generations` | GET | Generation fitness history |
| `/api/v1/experiments/{id}/subsets` | GET | Top discovered subsets |
| `/api/v1/experiments/{id}/pareto` | GET | Pareto frontier solutions |
| `/api/v1/features/operators` | GET | Operator catalog |
| `/api/v1/features/expression/validate` | POST | Validate DSL expression |
| `/api/v1/features/generate` | POST | Generate all features for dataset |
| `/api/v1/portfolio/backtest` | POST | Run long-short backtest |

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Async PostgreSQL URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for pub/sub |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/2` | Celery results |
| `DATASET_DIR` | `/data/datasets` | Dataset file storage |
| `LOG_LEVEL` | `INFO` | Logging level |

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, React 18, TanStack Query v5, Zustand v5, Recharts, Tailwind CSS |
| API | FastAPI, SQLAlchemy (async), Pydantic v2 |
| Workers | Celery, Redis |
| Database | PostgreSQL 15 |
| ML/Optimization | DEAP (GP + NSGA-II), scikit-learn, LightGBM |
| Math | NumPy, SciPy, pandas |
| Infrastructure | Docker Compose |
