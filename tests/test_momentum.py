import pandas as pd

from quant.backtest import run_backtest
from quant.strategies import MomentumStrategy


def test_momentum_signals_and_backtest():
    n = 60
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    # 前半段下跌、后半段上涨，动量信号应在后半段转多
    close = pd.Series([100 - i for i in range(30)] + [70 + i for i in range(30)], index=idx)
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
    strategy = MomentumStrategy(lookback=5)
    signals = strategy.generate_signals(data)
    assert signals.iloc[:5].sum() == 0  # 前 lookback 天无信号
    assert (signals.iloc[-10:] == 1.0).all()

    result = run_backtest(data, strategy)
    assert len(result.equity_curve) == n
    assert result.summary()["total_return"] is not None
