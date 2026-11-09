"""怎么输策略：双锚 Z 连续配比 + 风险 ETF 分仓（月频）。

相对「指定红策略」的核心优化
--------------------------------
1. 每日更新双锚 Z；按 Z 在超卖/超买区连续调节风险仓与银行仓
2. 风险仓不用个股，改为宽基/主题 ETF：
   创业板ETF、科创板ETF、科创50ETF、中证2000ETF 等
3. 购入优先级：近半年「调整偏离度」最高（相对半年高点回撤越大越优先）
4. 买入可分仓：按偏离度加权，或在 TopK 内等权拆分
5. 持仓结构按月末（BME）更新；月内沿用，避免频繁交易

仓位规则（月末决策，T+1）
------------------------
- Z 在 [-2, +2] 线性配比风险仓 / 银行仓：
  - z ≤ -2（超卖）：100% 风险 ETF
  - z 从 -2 向 +2 上升：陆续降低风险仓、提高银行仓
  - z ≥ +2（超买）：0% 风险、100% 银行腿
- 接近超卖（默认 z ≤ -1.5）：提醒加仓风险 ETF
- 接近超买（默认 z ≥ +1.5）：提醒减风险、加银行
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.strategies.dual_anchor import DEFAULT_BANKS, build_anchors


STRATEGY_ID = "zenmeshu"
STRATEGY_NAME = "怎么输策略"
STRATEGY_CODE = "zenmeshu"

# 风险 ETF 池（yfinance 代码 → 展示名）
DEFAULT_RISK_ETFS: dict[str, str] = {
    "159915.SZ": "创业板ETF",
    "588080.SS": "科创板ETF",
    "588000.SS": "科创50ETF",
    "563300.SS": "中证2000ETF",
}

DEFAULT_BANK_ETF = "512800.SS"  # 银行ETF（懒人防御腿）


@dataclass
class ZenmeshuConfig:
    """怎么输策略参数。"""

    z_window: int = 60
    trend_lookback: int = 20
    rebalance: str = "BME"
    # 超卖端：满仓风险
    z_full: float = -2.0
    # 超买端：满仓银行
    z_crisis: float = 2.0
    # 提醒带：接近超卖 / 接近超买
    z_buy: float = -1.5
    z_trim: float = 1.5
    # 近半年调整偏离（交易日约 126）
    adjust_lookback: int = 126
    # 分仓：最多买入 TopK 只 ETF
    top_k: int = 3
    # True=按调整偏离度加权；False=TopK 等权
    weight_by_adjust: bool = True
    risk_etfs: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_RISK_ETFS))
    bank_etf: str = DEFAULT_BANK_ETF
    bank_symbols: list[str] = field(default_factory=lambda: list(DEFAULT_BANKS))


def half_year_adjust_deviation(
    close: pd.DataFrame,
    date: pd.Timestamp,
    lookback: int = 126,
) -> pd.Series:
    """近半年调整偏离度 = 相对窗口内高点的回撤幅度（越大=调整越深）。"""
    hist = close.loc[:date]
    if len(hist) < max(20, lookback // 4):
        return pd.Series(dtype=float)
    window = hist.iloc[-lookback:]
    peak = window.max(axis=0)
    last = window.iloc[-1]
    # peak/last - 1；下跌越多分数越高；停牌/缺失剔除
    dev = (peak / last.replace(0, np.nan) - 1.0).replace([np.inf, -np.inf], np.nan)
    return dev.dropna().sort_values(ascending=False)


def _rebalance_dates(close: pd.DataFrame, freq: str) -> set:
    try:
        idx = close.resample(freq).last().dropna(how="all").index
    except ValueError:
        alt = {"BME": "BM", "ME": "M"}.get(freq, freq)
        idx = close.resample(alt).last().dropna(how="all").index
    return set(close.index.intersection(idx))


def _z_risk_share(z: float, cfg: ZenmeshuConfig) -> float:
    """Z → 风险仓比例。

    z ≤ z_full(-2) → 1.0（超卖满风险）
    z ≥ z_crisis(+2) → 0.0（超买满银行）
    中间线性递减：越靠近超买，风险仓越低、银行仓越高。
    """
    lo, hi = float(cfg.z_full), float(cfg.z_crisis)
    if hi <= lo:
        return 1.0 if z <= lo else 0.0
    if z <= lo:
        return 1.0
    if z >= hi:
        return 0.0
    return float(np.clip((hi - z) / (hi - lo), 0.0, 1.0))


def _alert_for_z(z: float, cfg: ZenmeshuConfig) -> str:
    if z <= cfg.z_full:
        return "超卖加深：满仓风险ETF"
    if z <= cfg.z_buy:
        return "靠近超卖：加仓风险ETF、减银行"
    if z >= cfg.z_crisis:
        return "超买：降风险股、满仓银行腿"
    if z >= cfg.z_trim:
        return "靠近超买：陆续降风险、加银行"
    return ""


def _leg_label(risk_share: float) -> str:
    if risk_share >= 0.7:
        return "risk_etf"
    if risk_share <= 0.3:
        return "bank"
    return "blend"


def select_risk_etfs(
    etf_close: pd.DataFrame,
    date: pd.Timestamp,
    cfg: ZenmeshuConfig,
) -> list[tuple[str, float, float]]:
    """返回 [(symbol, adjust_dev, weight_raw), ...] 已按偏离度排序并归一化权重。"""
    cols = [c for c in cfg.risk_etfs if c in etf_close.columns]
    if not cols:
        return []
    dev = half_year_adjust_deviation(etf_close[cols], date, cfg.adjust_lookback)
    if dev.empty:
        return []
    top = dev.head(min(cfg.top_k, len(dev)))
    if cfg.weight_by_adjust:
        score = top.clip(lower=0.0)
        if float(score.sum()) <= 1e-12:
            w = pd.Series(1.0 / len(top), index=top.index)
        else:
            w = score / score.sum()
    else:
        w = pd.Series(1.0 / len(top), index=top.index)
    return [(str(s), float(top.at[s]), float(w.at[s])) for s in top.index]


def _fill_bank(
    raw: pd.Series,
    bank_weight: float,
    dt: pd.Timestamp,
    etf_aligned: pd.DataFrame,
    cfg: ZenmeshuConfig,
    banks: list[str],
) -> None:
    if bank_weight <= 1e-12:
        return
    if (
        cfg.bank_etf in raw.index
        and cfg.bank_etf in etf_aligned.columns
        and pd.notna(etf_aligned.at[dt, cfg.bank_etf])
    ):
        raw.at[cfg.bank_etf] = bank_weight
    elif banks:
        w_b = bank_weight / len(banks)
        for s in banks:
            raw.at[s] = w_b


def generate_target_weights_zenmeshu(
    stock_close: pd.DataFrame,
    etf_close: pd.DataFrame,
    cfg: ZenmeshuConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成怎么输策略目标权重。

    Returns:
        weights: 列=股票+ETF 并集
        state: z/alert/leg/etf 明细等
    """
    cfg = cfg or ZenmeshuConfig()
    banks = [b for b in cfg.bank_symbols if b in stock_close.columns]

    anchors = build_anchors(
        stock_close,
        banks or None,
        z_window=cfg.z_window,
        trend_lookback=cfg.trend_lookback,
    )

    # 统一列空间
    all_cols = list(
        dict.fromkeys(
            list(stock_close.columns)
            + list(etf_close.columns)
            + list(cfg.risk_etfs)
            + ([cfg.bank_etf] if cfg.bank_etf else [])
        )
    )
    # 对齐交易日：以股票日历为主
    index = stock_close.index
    etf_aligned = etf_close.reindex(index).ffill()

    rebal = _rebalance_dates(stock_close, cfg.rebalance)
    weights = pd.DataFrame(0.0, index=index, columns=all_cols)
    rows: list[dict] = []

    prev_w = pd.Series(0.0, index=all_cols)
    held_leg = "bank"
    held_risk_share = 0.0
    held_risk_w = 0.0
    held_bank_w = 1.0
    last_picks: list[tuple[str, float, float]] = []

    for i, dt in enumerate(index):
        z = float(anchors.at[dt, "z"]) if pd.notna(anchors.at[dt, "z"]) else 0.0
        tr = float(anchors.at[dt, "trend"]) if pd.notna(anchors.at[dt, "trend"]) else 0.0
        is_rebal = dt in rebal or i == 0
        alert = _alert_for_z(z, cfg)
        signal_share = _z_risk_share(z, cfg)

        if is_rebal:
            risk_share = signal_share
            risk_budget = risk_share
            bank_budget = 1.0 - risk_share
            raw = pd.Series(0.0, index=all_cols)

            picks: list[tuple[str, float, float]] = []
            if risk_budget > 1e-12:
                picks = select_risk_etfs(etf_aligned, dt, cfg)
                if picks:
                    for sym, _dev, w_i in picks:
                        if sym in raw.index:
                            raw.at[sym] = risk_budget * w_i
                else:
                    # 无可用风险 ETF 时，预算并入银行
                    bank_budget += risk_budget
                    risk_budget = 0.0
                    risk_share = 0.0

            last_picks = picks
            _fill_bank(raw, bank_budget, dt, etf_aligned, cfg, banks)

            held_leg = _leg_label(risk_share)
            held_risk_share = risk_share
            held_risk_w = float(risk_budget)
            held_bank_w = float(bank_budget)
            prev_w = raw

        weights.loc[dt] = prev_w.to_numpy()

        pick_str = ",".join(
            f"{s}:{cfg.risk_etfs.get(s, s)}:{d:.2%}/{w:.0%}" for s, d, w in last_picks
        )
        rows.append(
            {
                "date": dt,
                "z": z,
                "trend": tr,
                "leg": held_leg,
                "signal_leg": _leg_label(signal_share),
                "risk_share": held_risk_share,
                "risk_weight": held_risk_w,
                "bank_weight": held_bank_w,
                "exposure": float(prev_w.sum()),
                "rebalance": bool(is_rebal),
                "alert": alert,
                "risk_etf_picks": pick_str,
            }
        )

    state = pd.DataFrame(rows).set_index("date")
    # 去掉全 0 列，减小体积
    weights = weights.loc[:, (weights.abs().sum(axis=0) > 0)]
    return weights, state
