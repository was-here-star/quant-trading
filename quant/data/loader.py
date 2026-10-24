"""行情数据加载."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yfinance as yf


def load_ohlcv(
    symbol: str,
    start: str | None = None,
    end: str | None = None,
    cache_dir: str | Path | None = None,
) -> pd.DataFrame:
    """下载并返回 OHLCV 日线数据。

    Args:
        symbol: 标的代码，如 AAPL、000001.SS
        start: 起始日期 YYYY-MM-DD
        end: 结束日期 YYYY-MM-DD
        cache_dir: 可选本地缓存目录

    Returns:
        索引为 DatetimeIndex 的 DataFrame，列含 Open/High/Low/Close/Volume
    """
    cache_path: Path | None = None
    if cache_dir is not None:
        cache_path = Path(cache_dir)
        cache_path.mkdir(parents=True, exist_ok=True)
        fname = f"{symbol}_{start or 'na'}_{end or 'na'}.parquet"
        file_path = cache_path / fname
        if file_path.exists():
            return pd.read_parquet(file_path)

    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, end=end, auto_adjust=True)
    if df.empty:
        raise ValueError(f"未获取到数据: {symbol}")

    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols].copy()
    df.index.name = "date"

    if cache_path is not None:
        df.to_parquet(cache_path / fname)

    return df
