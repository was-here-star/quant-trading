"""策略基类."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """策略接口：输入行情，输出目标仓位（-1 ~ 1）。"""

    name: str = "base"

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """生成目标仓位序列，索引与 data 对齐。"""
