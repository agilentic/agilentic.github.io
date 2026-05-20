from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from api.app.core.database import get_db
from api.app.models.models import Subset, Dataset, PortfolioResult as PortfolioResultModel
from api.app.schemas.schemas import BacktestRequest, PortfolioResultRead

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.post("/backtest", response_model=PortfolioResultRead)
async def run_backtest(req: BacktestRequest, db: AsyncSession = Depends(get_db)):
    feature_names = req.feature_names
    dataset_id = req.dataset_id
    target_col = req.target_col

    if req.subset_id:
        subset = await db.get(Subset, req.subset_id)
        if not subset:
            raise HTTPException(404, "Subset not found")
        feature_names = subset.feature_names
        from api.app.models.models import Experiment
        exp = await db.get(Experiment, subset.experiment_id)
        if exp:
            dataset_id = exp.dataset_id
            target_col = target_col or exp.target_col

    if not feature_names:
        raise HTTPException(400, "feature_names required")

    ds = await db.get(Dataset, dataset_id) if dataset_id else None
    if not ds:
        raise HTTPException(404, "Dataset not found")

    import pandas as pd
    df = pd.read_parquet(ds.file_path) if ds.file_path.endswith(".parquet") else pd.read_csv(ds.file_path)
    if "date" in df.columns and "ticker" in df.columns:
        df = df.set_index(["date", "ticker"])

    from engine.portfolio.constructor import PortfolioAgent
    agent = PortfolioAgent(df, target_col=target_col or "target_return_1d")
    metrics = agent.backtest_long_short_features(
        feature_names=[f for f in feature_names if f in df.columns],
        method=req.method,
        n_quantiles=req.n_quantiles,
    )

    result = PortfolioResultModel(
        subset_id=req.subset_id,
        method=req.method,
        **{k: v for k, v in metrics.items() if k in PortfolioResultModel.__table__.columns.keys()},
    )
    db.add(result)
    await db.commit()
    await db.refresh(result)
    return result


@router.get("/{result_id}", response_model=PortfolioResultRead)
async def get_result(result_id: str, db: AsyncSession = Depends(get_db)):
    r = await db.get(PortfolioResultModel, result_id)
    if not r:
        raise HTTPException(404, "Result not found")
    return r
