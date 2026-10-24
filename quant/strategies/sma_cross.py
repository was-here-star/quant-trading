"""双均线交叉策略."""

from __future__ import annotations

import pandas as pd

from quant.strategies.base import Strategy


class SMACrossStrategy(Strategy):
    """快线上穿慢线做多，下穿空仓（或做空）。"""

    name = "sma"

    def __init__(self, fast: int = 10, slow: int = 30, allow_short: bool = False) -> None:
        if fast >= slow:
            raise ValueError("fast 必须小于 slow")
        self.fast = fast
        self.slow = slow
        self.allow_short = allow_short

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        fast_ma = close.rolling(self.fast).mean()
        slow_ma = close.rolling(self.slow).mean()
        long_signal = (fast_ma > slow_ma).astype(float)
        if self.allow_short:
            signal = long_signal * 2 - 1  # 1 或 -1
        else:
            signal = long_signal  # 1 或 0
        signal.name = "position"
        return signal.fillna(0.0)
