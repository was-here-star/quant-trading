"""简单动量策略：过去 N 日收益为正则做多，否则空仓。"""

from __future__ import annotations

import pandas as pd

from quant.strategies.base import Strategy


class MomentumStrategy(Strategy):
    """N 日动量：lookback 日累计收益 > 0 持有多头，否则空仓。"""

    name = "momentum"

    def __init__(self, lookback: int = 20) -> None:
        if lookback < 1:
            raise ValueError("lookback 必须 >= 1")
        self.lookback = lookback

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        mom = close.pct_change(self.lookback)
        signal = (mom > 0).astype(float)
        signal.name = "position"
        return signal.fillna(0.0)
