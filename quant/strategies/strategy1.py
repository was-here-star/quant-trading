"""策略1：双锚偏离度截取（类 CTA）。

来源文案要点
------------
市场规律不在故事，在价格偏离度；截取偏离度数值 = 截取流动性溢价。
两个核心价格指数：
  - 银行算术平均股价 = 分配权
  - 全A平均股价     = 定价权
两者偏离度 → 过热/过冷 → 情绪与流动性 → 牛熊。
A股难做空：用「风险腿 ↔ 银行腿」切换，向上向下都能参与。
底层类 CTA；样本缩到 Top10/Top50 增强收益。

规则（默认月末调仓 BME，月内不换仓；T+1 生效）
----------------------------------------------
1. ratio = 全A均价 / 银行均价
2. z = zscore(log(ratio), 60)
3. 月末：比价20日 > 0 → 100% 风险腿（流动性前2N → 动量前N）
4. 月末：比价20日 ≤ 0 → 100% 银行腿（银行等权）
5. 月末：|z| > 2 → 总仓位 × 0.5
6. 非月末：沿用上月末持仓，不频繁操作

策略一熔断版（STRATEGY_BREAKER_NAME，见 generate_target_weights_breaker）
----------------------------------------------------------------------
A. 风险腿段内回撤 ≤ -8% → 强制切银行
B. 近5日累计落后银行腿 ≥ 3% → 强制切银行
C. 组合单日 ≤ -3% → 当日目标仓位上限 50%（T+1 生效）
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from quant.strategies.dual_anchor import (
    DEFAULT_BANKS,
    DualAnchorConfig,
    build_anchors,
    generate_target_weights,
    select_risk_names,
)

STRATEGY_ID = 1
STRATEGY_NAME = "指定红策略"
STRATEGY_CODE = "strategy1"

# 优化版正式名「怎么输策略」——实现见 quant.strategies.zenmeshu（ETF 分仓）
# 下列常量保留兼容旧熔断版接口命名
STRATEGY_BREAKER_ID = "zenmeshu"
STRATEGY_BREAKER_NAME = "怎么输策略"
STRATEGY_BREAKER_CODE = "zenmeshu"

# 策略1默认参数
Strategy1Config = DualAnchorConfig


@dataclass
class BreakerConfig:
    """策略一熔断版参数（默认启用 A+B+C 全套）。

    A) seg_drawdown: 风险段回撤阈值（默认 -8%）→ 切银行
    B) underperf_*: 近窗跑输银行（默认 5日、落后 3%）→ 切银行
    C) day_loss / day_loss_scale: 单日大亏降仓（默认 -3% → 仓位 50%）

    平滑 / 自适应（adaptive=True）
    --------------------------------
    - 用双锚比价趋势 + 风险相对银行的20日超额，识别强/弱风险年(段)
    - 强风险段：放宽 A/B/C 阈值，B 需连续确认，先软降仓再硬切
    - 弱风险段：收紧阈值，更快保护
    - 常态：B 也需连续确认天数，减少来回打脸
    """

    seg_drawdown: float = -0.08
    underperf_window: int = 5
    underperf_gap: float = -0.03
    day_loss: float = -0.03
    day_loss_scale: float = 0.5
    # 平滑
    underperf_confirm_days: int = 1
    # 自适应
    adaptive: bool = False
    regime_trend_strong: float = 0.03
    regime_trend_weak: float = 0.0
    regime_excess_window: int = 20
    # 强风险段阈值（更松）
    strong_seg_drawdown: float = -0.12
    strong_underperf_gap: float = -0.08
    strong_day_loss: float = -0.045
    strong_underperf_confirm_days: int = 2
    strong_soft_scale: float = 0.6  # B触发先降到该仓位，未达更差才硬切
    # 弱风险段阈值（更严）
    weak_seg_drawdown: float = -0.06
    weak_underperf_gap: float = -0.02
    weak_day_loss: float = -0.025
    weak_underperf_confirm_days: int = 1


def _resolve_breaker_thresholds(
    br: BreakerConfig,
    trend: float,
    trend_pos_share: float,
    excess_20: float,
) -> tuple[str, float, float, float, int, bool]:
    """返回 regime, seg_dd, underperf_gap, day_loss, confirm_days, soft_underperf。

    体制以双锚比价趋势为主（与策略1同源），超额收益仅作辅助，避免全市场噪声误判。
    """
    if not br.adaptive:
        return (
            "fixed",
            br.seg_drawdown,
            br.underperf_gap,
            br.day_loss,
            br.underperf_confirm_days,
            False,
        )

    # 强风险：趋势向上且近段多数时间为正（风险腿友好）
    if trend >= br.regime_trend_strong and trend_pos_share >= 0.6:
        return (
            "strong",
            br.strong_seg_drawdown,
            br.strong_underperf_gap,
            br.strong_day_loss,
            br.strong_underperf_confirm_days,
            True,
        )
    # 弱风险：趋势为负，或趋势走弱且风险代理显著跑输银行
    if trend <= br.regime_trend_weak or (
        trend < br.regime_trend_strong and excess_20 <= -0.05 and trend_pos_share <= 0.4
    ):
        return (
            "weak",
            br.weak_seg_drawdown,
            br.weak_underperf_gap,
            br.weak_day_loss,
            br.weak_underperf_confirm_days,
            False,
        )
    # 常态：平滑确认，避免毛刺
    return (
        "normal",
        br.seg_drawdown,
        br.underperf_gap,
        br.day_loss,
        max(2, br.underperf_confirm_days),
        False,
    )


def generate_target_weights_breaker(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    cfg: DualAnchorConfig | None = None,
    breaker: BreakerConfig | None = None,
    bank_symbols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """策略一熔断版：在策略1信号上叠加 A/B/C 熔断（可自适应平滑）。"""
    cfg = cfg or DualAnchorConfig()
    br = breaker or BreakerConfig()
    banks = bank_symbols or DEFAULT_BANKS
    bank_cols = [c for c in banks if c in close.columns]
    non_bank_cols = [c for c in close.columns if c not in set(bank_cols)]

    base_w, base_st = generate_target_weights(
        close, volume, cfg=cfg, bank_symbols=banks
    )
    rets = close.pct_change(fill_method=None).fillna(0.0)
    bank_ret = close[bank_cols].pct_change(fill_method=None).mean(axis=1).fillna(0.0)
    # 风险代理：非银行等权（仅用于体制判断，避免前视）
    risk_proxy = (
        close[non_bank_cols].pct_change(fill_method=None).mean(axis=1).fillna(0.0)
        if non_bank_cols
        else bank_ret * 0.0
    )

    out_w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    rows: list[dict] = []

    prev_w = pd.Series(0.0, index=close.columns)
    prev_leg = "bank"
    in_risk_seg = False
    risk_nav = 1.0
    risk_peak = 1.0
    underperf_streak = 0

    for i, dt in enumerate(close.index):
        day_r = float((prev_w * rets.loc[dt]).sum()) if i > 0 else 0.0

        base_leg = str(base_st.at[dt, "leg"])
        base_exp = float(base_st.at[dt, "exposure"])
        z = float(base_st.at[dt, "z"]) if pd.notna(base_st.at[dt, "z"]) else 0.0
        tr = float(base_st.at[dt, "trend"]) if pd.notna(base_st.at[dt, "trend"]) else 0.0
        risk_names = [
            s
            for s in str(base_st.at[dt, "risk_names"]).split(",")
            if s and s in close.columns
        ]
        if not risk_names:
            for j in range(i, -1, -1):
                nm = str(base_st["risk_names"].iloc[j])
                risk_names = [s for s in nm.split(",") if s and s in close.columns]
                if risk_names:
                    break

        # 体制：比价趋势持续性 + 风险代理相对银行超额（辅助）
        w_ex = br.regime_excess_window
        if i + 1 >= w_ex:
            win = close.index[i - w_ex + 1 : i + 1]
            excess_20 = float((1 + risk_proxy.loc[win]).prod() - 1) - float(
                (1 + bank_ret.loc[win]).prod() - 1
            )
            tr_hist = base_st.loc[win, "trend"].astype(float)
            trend_pos_share = float((tr_hist > 0).mean())
        else:
            excess_20 = 0.0
            trend_pos_share = 1.0 if tr > 0 else 0.0

        regime, thr_seg, thr_gap, thr_day, confirm_n, soft_b = _resolve_breaker_thresholds(
            br, tr, trend_pos_share, excess_20
        )

        leg = base_leg
        exp = base_exp
        reasons: list[str] = []

        # A. 风险段回撤熔断
        if prev_leg == "risk":
            if not in_risk_seg:
                in_risk_seg = True
                risk_nav = 1.0
                risk_peak = 1.0
            risk_nav *= 1.0 + day_r
            risk_peak = max(risk_peak, risk_nav)
            seg_dd = risk_nav / risk_peak - 1.0 if risk_peak > 0 else 0.0
            if seg_dd <= thr_seg:
                leg = "bank"
                reasons.append(f"seg_dd:{seg_dd:.2%}")
                in_risk_seg = False
                risk_nav = 1.0
                risk_peak = 1.0
                underperf_streak = 0
        else:
            in_risk_seg = False
            risk_nav = 1.0
            risk_peak = 1.0

        # B. 近窗风险腿跑输银行（可确认天数 + 强体制软降仓）
        gap = float("nan")
        if leg == "risk" and risk_names and i >= br.underperf_window:
            window = close.index[i - br.underperf_window + 1 : i + 1]
            r_risk = rets.loc[window, risk_names].mean(axis=1)
            r_bank = bank_ret.loc[window]
            gap = float((1 + r_risk).prod() - 1) - float((1 + r_bank).prod() - 1)
            if gap <= thr_gap:
                underperf_streak += 1
            else:
                underperf_streak = 0

            if underperf_streak >= confirm_n:
                if soft_b and gap > thr_gap * 1.5:
                    # 强风险段：先软降仓，不立刻切银行
                    exp = min(exp, br.strong_soft_scale)
                    reasons.append(f"underperf_soft:{gap:.2%}")
                else:
                    leg = "bank"
                    reasons.append(f"underperf:{gap:.2%}")
                    in_risk_seg = False
                    underperf_streak = 0
        else:
            underperf_streak = 0

        # C. 单日大亏 → 仓位上限
        if day_r <= thr_day:
            exp = min(exp, br.day_loss_scale)
            reasons.append(f"day_loss:{day_r:.2%}")

        raw = pd.Series(0.0, index=close.columns)
        if leg == "risk" and risk_names:
            w = exp / len(risk_names)
            for s in risk_names:
                raw.at[s] = w
        elif bank_cols:
            w = exp / len(bank_cols)
            for s in bank_cols:
                raw.at[s] = w

        out_w.loc[dt] = raw.to_numpy()
        prev_w = raw
        prev_leg = leg

        rows.append(
            {
                "date": dt,
                "z": z,
                "trend": tr,
                "leg": leg,
                "base_leg": base_leg,
                "exposure": exp,
                "day_realized": day_r,
                "breaker": "|".join(reasons),
                "regime": regime,
                "excess_20": excess_20,
                "underperf_streak": underperf_streak,
                "risk_names": ",".join(risk_names) if leg == "risk" else "",
            }
        )

    state = pd.DataFrame(rows).set_index("date")
    return out_w, state


__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "STRATEGY_CODE",
    "STRATEGY_BREAKER_ID",
    "STRATEGY_BREAKER_NAME",
    "STRATEGY_BREAKER_CODE",
    "Strategy1Config",
    "BreakerConfig",
    "DEFAULT_BANKS",
    "DualAnchorConfig",
    "build_anchors",
    "generate_target_weights",
    "generate_target_weights_breaker",
    "select_risk_names",
]
