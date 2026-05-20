import os
import uuid
import shutil
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from api.app.core.database import get_db
from api.app.core.config import settings
from api.app.models.models import Dataset
from api.app.schemas.schemas import DatasetRead

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("/", response_model=list[DatasetRead])
async def list_datasets(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Dataset).order_by(Dataset.created_at.desc()))
    return result.scalars().all()


@router.post("/sample", response_model=DatasetRead)
async def create_sample(db: AsyncSession = Depends(get_db)):
    from engine.agents.data_agent import DataAgent
    agent = DataAgent()
    df = agent.generate_sample_data(n_assets=50, n_days=756)
    os.makedirs(settings.dataset_dir, exist_ok=True)
    ds_id = str(uuid.uuid4())
    path = os.path.join(settings.dataset_dir, f"{ds_id}.parquet")
    df.reset_index().to_parquet(path, index=False)
    dates = df.index.get_level_values("date").unique()
    tickers = df.index.get_level_values("ticker").unique()
    ds = Dataset(
        id=ds_id,
        name="Sample OHLCV — 50 assets × 3 years",
        file_path=path,
        row_count=len(df),
        asset_count=len(tickers),
        date_range={"start": str(dates.min()), "end": str(dates.max()), "trading_days": len(dates)},
        columns=list(df.columns),
        is_sample=True,
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return ds


@router.post("/upload", response_model=DatasetRead)
async def upload_dataset(
    file: UploadFile = File(...),
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    os.makedirs(settings.dataset_dir, exist_ok=True)
    ds_id = str(uuid.uuid4())
    ext = os.path.splitext(file.filename or "data.csv")[1] or ".csv"
    path = os.path.join(settings.dataset_dir, f"{ds_id}{ext}")
    with open(path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    import pandas as pd
    try:
        df = pd.read_parquet(path) if ext == ".parquet" else pd.read_csv(path)
    except Exception as e:
        os.remove(path)
        raise HTTPException(400, f"Failed to parse file: {e}")
    ds = Dataset(
        id=ds_id,
        name=name,
        file_path=path,
        row_count=len(df),
        asset_count=df["ticker"].nunique() if "ticker" in df.columns else None,
        columns=list(df.columns),
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return ds


@router.get("/{dataset_id}", response_model=DatasetRead)
async def get_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    ds = await db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    return ds


@router.get("/{dataset_id}/preview")
async def preview_dataset(dataset_id: str, n_rows: int = 10, db: AsyncSession = Depends(get_db)):
    ds = await db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    import pandas as pd
    df = pd.read_parquet(ds.file_path) if ds.file_path.endswith(".parquet") else pd.read_csv(ds.file_path)
    sample = df.head(n_rows)
    return {"columns": list(sample.columns), "rows": sample.fillna("").to_dict(orient="records")}


@router.get("/{dataset_id}/stats")
async def dataset_stats(dataset_id: str, db: AsyncSession = Depends(get_db)):
    ds = await db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    import pandas as pd
    import numpy as np
    df = pd.read_parquet(ds.file_path) if ds.file_path.endswith(".parquet") else pd.read_csv(ds.file_path)
    stats = {}
    for col in df.columns:
        s = df[col]
        col_stats: dict = {"dtype": str(s.dtype), "non_null_count": int(s.notna().sum())}
        if s.dtype in [np.float64, np.float32, np.int64, np.int32]:
            col_stats.update({
                "mean": float(s.mean()) if not np.isnan(s.mean()) else None,
                "std": float(s.std()) if not np.isnan(s.std()) else None,
                "min": float(s.min()),
                "max": float(s.max()),
            })
        stats[col] = col_stats
    return {"row_count": len(df), "column_stats": stats}


@router.delete("/{dataset_id}")
async def delete_dataset(dataset_id: str, db: AsyncSession = Depends(get_db)):
    ds = await db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    if ds.file_path and os.path.exists(ds.file_path):
        os.remove(ds.file_path)
    await db.delete(ds)
    await db.commit()
    return {"ok": True}
