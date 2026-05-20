import numpy as np
import pandas as pd
from scipy import stats


def distance_correlation(x: np.ndarray, y: np.ndarray, sample_size: int = 1000) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    x, y = x[mask], y[mask]
    if len(x) < 10:
        return 0.0
    if len(x) > sample_size:
        idx = np.random.choice(len(x), sample_size, replace=False)
        x, y = x[idx], y[idx]
    n = len(x)
    a = np.abs(x[:, None] - x[None, :])
    b = np.abs(y[:, None] - y[None, :])
    a_row = a.mean(axis=1)
    a_col = a.mean(axis=0)
    a_mean = a.mean()
    b_row = b.mean(axis=1)
    b_col = b.mean(axis=0)
    b_mean = b.mean()
    A = a - a_row[:, None] - a_col[None, :] + a_mean
    B = b - b_row[:, None] - b_col[None, :] + b_mean
    dcov2_xy = (A * B).mean()
    dcov2_xx = (A * A).mean()
    dcov2_yy = (B * B).mean()
    denom = np.sqrt(dcov2_xx * dcov2_yy)
    if denom <= 0:
        return 0.0
    return float(np.sqrt(max(0, dcov2_xy / denom)))


def conditional_mutual_information(
    x: np.ndarray, y: np.ndarray, z: np.ndarray, n_bins: int = 8
) -> float:
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    if len(x) < 20:
        return 0.0
    xd = pd.qcut(x, n_bins, labels=False, duplicates="drop")
    yd = pd.qcut(y, n_bins, labels=False, duplicates="drop")
    zd = pd.qcut(z, n_bins, labels=False, duplicates="drop")
    xyz = pd.DataFrame({"x": xd, "y": yd, "z": zd}).dropna()
    if len(xyz) < 10:
        return 0.0
    p_xyz = xyz.groupby(["x", "y", "z"]).size() / len(xyz)
    p_xz = xyz.groupby(["x", "z"]).size() / len(xyz)
    p_yz = xyz.groupby(["y", "z"]).size() / len(xyz)
    p_z = xyz.groupby("z").size() / len(xyz)
    cmi = 0.0
    for (xi, yi, zi), p in p_xyz.items():
        if p <= 0:
            continue
        pxz = p_xz.get((xi, zi), 0)
        pyz = p_yz.get((yi, zi), 0)
        pz = p_z.get(zi, 0)
        if pxz > 0 and pyz > 0 and pz > 0:
            cmi += p * np.log(p * pz / (pxz * pyz) + 1e-12)
    return float(max(0, cmi))


def cross_sectional_ic(feature: pd.Series, target: pd.Series, dates: pd.Index) -> pd.Series:
    ics = []
    date_list = []
    for d in dates:
        try:
            f = feature.xs(d, level="date") if hasattr(feature.index, "levels") else feature[d]
            t = target.xs(d, level="date") if hasattr(target.index, "levels") else target[d]
        except KeyError:
            continue
        combined = pd.concat([f, t], axis=1).dropna()
        if len(combined) < 5:
            continue
        ic, _ = stats.spearmanr(combined.iloc[:, 0], combined.iloc[:, 1])
        if np.isfinite(ic):
            ics.append(ic)
            date_list.append(d)
    return pd.Series(ics, index=date_list)


def sharpe_ratio(returns: np.ndarray, freq: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) < 2 or r.std() == 0:
        return 0.0
    return float(r.mean() / r.std() * np.sqrt(freq))


def max_drawdown(returns: np.ndarray) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return 0.0
    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / (peak + 1e-10)
    return float(dd.min())
