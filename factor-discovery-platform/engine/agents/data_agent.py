import numpy as np
import pandas as pd


class DataAgent:
    def generate_sample_data(self, n_assets: int = 50, n_days: int = 756, seed: int = 42) -> pd.DataFrame:
        rng = np.random.default_rng(seed)
        dates = pd.bdate_range("2021-01-01", periods=n_days)
        tickers = [f"ASSET_{i:03d}" for i in range(n_assets)]
        sectors = {t: rng.choice(["Tech", "Finance", "Energy", "Health", "Consumer"]) for t in tickers}
        records = []
        for ticker in tickers:
            price = 100.0
            vol_regime = 0.15
            for date in dates:
                if rng.random() < 0.05:
                    vol_regime = rng.uniform(0.10, 0.35)
                ret = rng.normal(0.0003, vol_regime / np.sqrt(252))
                price *= (1 + ret)
                volume = rng.lognormal(15, 1) * (1 + abs(ret) * 5)
                high = price * (1 + abs(rng.normal(0, 0.005)))
                low = price * (1 - abs(rng.normal(0, 0.005)))
                records.append({
                    "date": date, "ticker": ticker,
                    "open": price * (1 + rng.normal(0, 0.002)),
                    "high": high, "low": low, "close": price, "volume": volume,
                    "sector": sectors[ticker],
                })
        df = pd.DataFrame(records).set_index(["date", "ticker"])
        # Add a simple forward return target
        close = df["close"].unstack("ticker")
        target = close.pct_change(1).shift(-1).stack()
        target.name = "target_return_1d"
        df = df.join(target)
        return df
