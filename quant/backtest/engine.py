"""简易回测引擎."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from quant.strategies.base import Strategy


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    positions: pd.Series
    returns: pd.Series
    total_return: float
    sharpe: float
    max_drawdown: float

    def summary(self) -> dict[str, float]:
        return {
            "total_return": self.total_return,
            "sharpe": self.sharpe,
            "max_drawdown": self.max_drawdown,
        }


def run_backtest(
    data: pd.DataFrame,
    strategy: Strategy,
    initial_capital: float = 100_000.0,
    fee_bps: float = 1.0,
) -> BacktestResult:
    """按日线收盘价换仓回测。

    Args:
        data: 含 close 列的行情
        strategy: 策略实例
        initial_capital: 初始资金
        fee_bps: 单边手续费（基点），默认 1bp
    """
    positions = strategy.generate_signals(data)
    close = data["close"].astype(float)
    ret = close.pct_change().fillna(0.0)

    # 信号 T 日收盘生成，T+1 生效
    pos = positions.shift(1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    fee = turnover * (fee_bps / 10_000.0)
    strategy_ret = pos * ret - fee

    equity = (1.0 + strategy_ret).cumprod() * initial_capital
    total_return = float(equity.iloc[-1] / initial_capital - 1.0)

    vol = strategy_ret.std()
    sharpe = float(strategy_ret.mean() / vol * np.sqrt(252)) if vol > 0 else 0.0

    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    max_drawdown = float(drawdown.min())

    return BacktestResult(
        equity_curve=equity,
        positions=pos,
        returns=strategy_ret,
        total_return=total_return,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
    )
