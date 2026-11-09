"""双锚偏离度截取（策略1 核心实现）。

正式编号见 quant.strategies.strategy1（STRATEGY_ID=1）。

文案 → 规则映射
----------------
- 不做故事/龙头叙事，只做价格偏离度
- 双锚：银行算术均价（分配权） vs 全A算术均价（定价权）
- 偏离度 = 两者比价的标准化距离；截取偏离度 = 截取流动性溢价
- 向上/向下都能赚：A股难做空 → 用「风险腿 ↔ 银行腿」切换代替裸空
- 类 CTA：跟随比价趋势；极端偏离时降杠杆（国内节流/钟摆）
- 缩样本：流动性池内取 TopN（10 增强 / 50 稳健）

信号（日频计算，周频调仓）
--------------------------
1. ratio_t = AllA_avg / Bank_avg
2. z_t = zscore(log(ratio), window=60)
3. trend_t = sign(ratio_t / ratio_{t-20} - 1)   # 比价 20 日动量

仓位
----
- trend > 0 → 100% 风险腿（TopN：先按 20 日成交额筛 2N，再按 20 日动量取 N）
- trend ≤ 0 → 100% 银行腿（银行股等权）
- |z| > z_crisis → 总仓位 × 0.5（流动性危机防护）
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


DEFAULT_BANKS = [
    "600000.SS",
    "600016.SS",
    "600036.SS",
    "600919.SS",
    "601166.SS",
    "601288.SS",
    "601328.SS",
    "601398.SS",
    "601988.SS",
    "000001.SZ",
    "002142.SZ",
]


@dataclass
class DualAnchorConfig:
    z_window: int = 60
    trend_lookback: int = 20
    liq_lookback: int = 20
    mom_lookback: int = 20
    top_n: int = 10
    z_crisis: float = 2.0
    crisis_scale: float = 0.5
    # 默认月频：月末（交易日）调仓，月内不换仓
    rebalance: str = "BME"


def build_anchors(
    close: pd.DataFrame,
    bank_symbols: list[str] | None = None,
    z_window: int = 60,
    trend_lookback: int = 20,
) -> pd.DataFrame:
    """构建双锚与偏离度。"""
    banks = bank_symbols or DEFAULT_BANKS
    bank_cols = [c for c in banks if c in close.columns]
    if not bank_cols:
        raise ValueError("close 中无银行标的，无法构建分配权锚")

    bank_avg = close[bank_cols].mean(axis=1, skipna=True)
    alla_avg = close.mean(axis=1, skipna=True)
    ratio = alla_avg / bank_avg
    log_ratio = np.log(ratio)
    mu = log_ratio.rolling(z_window, min_periods=z_window).mean()
    sd = log_ratio.rolling(z_window, min_periods=z_window).std()
    z = (log_ratio - mu) / sd.replace(0, np.nan)
    trend = ratio.pct_change(trend_lookback)

    return pd.DataFrame(
        {
            "bank_avg": bank_avg,
            "alla_avg": alla_avg,
            "ratio": ratio,
            "z": z,
            "trend": trend,
        },
        index=close.index,
    )


def select_risk_names(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    date: pd.Timestamp,
    top_n: int,
    exclude: set[str],
    liq_lookback: int = 20,
    mom_lookback: int = 20,
) -> list[str]:
    """流动性 → 动量 两段式选股（只用 date 及之前数据）。"""
    hist_c = close.loc[:date]
    hist_v = volume.loc[:date]
    need = max(liq_lookback, mom_lookback) + 1
    if len(hist_c) < need:
        return []

    amount = (hist_c.iloc[-liq_lookback:] * hist_v.iloc[-liq_lookback:]).mean().dropna()
    amount = amount[[s for s in amount.index if s not in exclude]]
    if amount.empty:
        return []

    pool = amount.nlargest(min(len(amount), max(top_n * 2, top_n))).index.tolist()
    px = hist_c[pool].iloc[-(mom_lookback + 1) :]
    if len(px) < mom_lookback + 1:
        return pool[:top_n]
    mom = (px.iloc[-1] / px.iloc[0] - 1.0).dropna().sort_values(ascending=False)
    return mom.head(top_n).index.tolist()


def generate_target_weights(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    cfg: DualAnchorConfig | None = None,
    bank_symbols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成目标权重（收盘决策）；回测时请 shift(1) 作为 T+1 生效。

    仅在调仓日（默认月末 BME）根据信号换腿/换股；
    非调仓日沿用上一调仓日权重，月内不频繁操作。

    Returns:
        weights: 列=标的，行=日期，和为总仓位
        state: 含 z/trend/leg/exposure/rebalance 的状态表
    """
    cfg = cfg or DualAnchorConfig()
    banks = bank_symbols or DEFAULT_BANKS
    bank_cols = [c for c in banks if c in close.columns]
    exclude = set(bank_cols)

    anchors = build_anchors(
        close,
        banks,
        z_window=cfg.z_window,
        trend_lookback=cfg.trend_lookback,
    )

    try:
        rebal_dates = close.resample(cfg.rebalance).last().dropna(how="all").index
    except ValueError:
        # 兼容旧版 pandas 频率名
        alt = {"BME": "BM", "ME": "M"}.get(cfg.rebalance, cfg.rebalance)
        rebal_dates = close.resample(alt).last().dropna(how="all").index
    rebal_dates = set(close.index.intersection(rebal_dates))

    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    rows: list[dict] = []
    last_risk: list[str] = []
    held_leg = "bank"
    held_exp = 1.0
    prev_w = pd.Series(0.0, index=close.columns)

    for i, dt in enumerate(close.index):
        z = float(anchors.at[dt, "z"]) if pd.notna(anchors.at[dt, "z"]) else 0.0
        tr = float(anchors.at[dt, "trend"]) if pd.notna(anchors.at[dt, "trend"]) else 0.0
        is_rebal = dt in rebal_dates or i == 0

        if is_rebal:
            held_exp = cfg.crisis_scale if abs(z) > cfg.z_crisis else 1.0
            held_leg = "risk" if tr > 0 else "bank"
            picks = select_risk_names(
                close,
                volume,
                dt,
                top_n=cfg.top_n,
                exclude=exclude,
                liq_lookback=cfg.liq_lookback,
                mom_lookback=cfg.mom_lookback,
            )
            if picks:
                last_risk = picks

            raw = pd.Series(0.0, index=close.columns)
            if held_leg == "risk" and last_risk:
                w = held_exp / len(last_risk)
                for s in last_risk:
                    raw.at[s] = w
            elif bank_cols:
                w = held_exp / len(bank_cols)
                for s in bank_cols:
                    raw.at[s] = w
            prev_w = raw
        # 非调仓日：沿用上一调仓权重

        weights.loc[dt] = prev_w.to_numpy()

        rows.append(
            {
                "date": dt,
                "z": z,
                "trend": tr,
                "leg": held_leg,
                "exposure": held_exp,
                "rebalance": bool(is_rebal),
                "signal_leg": "risk" if tr > 0 else "bank",
                "risk_names": ",".join(last_risk) if held_leg == "risk" else "",
            }
        )

    state = pd.DataFrame(rows).set_index("date")
    return weights, state
