from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from api.app.core.database import get_db

router = APIRouter(prefix="/features", tags=["features"])


@router.get("/operators")
async def list_operators():
    from engine.factors.operators import OperatorCatalog
    catalog = OperatorCatalog()
    return catalog.get_catalog()


@router.post("/expression/validate")
async def validate_expression(body: dict):
    expr = body.get("expression", "")
    from engine.factors.operators import OperatorCatalog
    catalog = OperatorCatalog()
    result = catalog.validate_expression(expr)
    return result


@router.post("/generate")
async def generate_features(body: dict, db: AsyncSession = Depends(get_db)):
    dataset_id = body.get("dataset_id")
    max_features = body.get("max_features", 200)
    if not dataset_id:
        raise HTTPException(400, "dataset_id required")
    from api.app.models.models import Dataset
    ds = await db.get(Dataset, dataset_id)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    import pandas as pd
    df = pd.read_parquet(ds.file_path) if ds.file_path.endswith(".parquet") else pd.read_csv(ds.file_path)
    if "date" in df.columns and "ticker" in df.columns:
        df = df.set_index(["date", "ticker"])
    from engine.factors.feature_factory import FeatureFactoryAgent
    factory = FeatureFactoryAgent(df)
    features_df = factory.generate_primitive_features()
    return {"count": len(features_df.columns), "features": list(features_df.columns)[:max_features]}
