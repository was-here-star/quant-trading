import pandas as pd

from quant.backtest import run_backtest
from quant.strategies import SMACrossStrategy


def test_sma_backtest_runs():
    n = 80
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    # 构造先跌后涨的序列，保证均线有交叉
    close = pd.Series(range(n), index=idx, dtype=float) + 100
    data = pd.DataFrame(
        {
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1_000_000,
        },
        index=idx,
    )
    strategy = SMACrossStrategy(fast=5, slow=20)
    result = run_backtest(data, strategy)
    assert len(result.equity_curve) == n
    assert "total_return" in result.summary()
