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

规则（周频调仓，T+1 生效）
--------------------------
1. ratio = 全A均价 / 银行均价
2. z = zscore(log(ratio), 60)
3. 比价20日 > 0 → 100% 风险腿（流动性前2N → 动量前N）
4. 比价20日 ≤ 0 → 100% 银行腿（银行等权）
5. |z| > 2 → 总仓位 × 0.5

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
STRATEGY_NAME = "双锚偏离度截取"
STRATEGY_CODE = "strategy1"

# 策略一熔断版（正式留档名）
STRATEGY_BREAKER_ID = "1-breaker"
STRATEGY_BREAKER_NAME = "策略一熔断版"
STRATEGY_BREAKER_CODE = "strategy1_breaker"

# 策略1默认参数
Strategy1Config = DualAnchorConfig


@dataclass
class BreakerConfig:
    """策略一熔断版参数（默认启用 A+B+C 全套）。

    A) seg_drawdown: 风险段回撤阈值（默认 -8%）→ 切银行
    B) underperf_*: 近窗跑输银行（默认 5日、落后 3%）→ 切银行
    C) day_loss / day_loss_scale: 单日大亏降仓（默认 -3% → 仓位 50%）
    """

    seg_drawdown: float = -0.08
    underperf_window: int = 5
    underperf_gap: float = -0.03
    day_loss: float = -0.03
    day_loss_scale: float = 0.5


def generate_target_weights_breaker(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    cfg: DualAnchorConfig | None = None,
    breaker: BreakerConfig | None = None,
    bank_symbols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """策略一熔断版：在策略1信号上叠加 A/B/C 熔断。"""
    cfg = cfg or DualAnchorConfig()
    br = breaker or BreakerConfig()
    banks = bank_symbols or DEFAULT_BANKS
    bank_cols = [c for c in banks if c in close.columns]

    base_w, base_st = generate_target_weights(
        close, volume, cfg=cfg, bank_symbols=banks
    )
    rets = close.pct_change(fill_method=None).fillna(0.0)
    bank_ret = close[bank_cols].pct_change(fill_method=None).mean(axis=1).fillna(0.0)

    out_w = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    rows: list[dict] = []

    prev_w = pd.Series(0.0, index=close.columns)
    prev_leg = "bank"
    in_risk_seg = False
    risk_nav = 1.0
    risk_peak = 1.0

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
        # 若当日 base 是 bank，risk_names 为空；用最近风险池近似（取 base 权重里非银行）
        if not risk_names:
            for j in range(i, -1, -1):
                nm = str(base_st["risk_names"].iloc[j])
                risk_names = [s for s in nm.split(",") if s and s in close.columns]
                if risk_names:
                    break

        leg = base_leg
        exp = base_exp
        reasons: list[str] = []

        # A. 风险段回撤熔断：用「昨日持仓在今日」的实现收益更新段净值
        if prev_leg == "risk":
            if not in_risk_seg:
                in_risk_seg = True
                risk_nav = 1.0
                risk_peak = 1.0
            risk_nav *= 1.0 + day_r
            risk_peak = max(risk_peak, risk_nav)
            seg_dd = risk_nav / risk_peak - 1.0 if risk_peak > 0 else 0.0
            if seg_dd <= br.seg_drawdown:
                leg = "bank"
                reasons.append(f"seg_dd:{seg_dd:.2%}")
                in_risk_seg = False
                risk_nav = 1.0
                risk_peak = 1.0
        else:
            in_risk_seg = False
            risk_nav = 1.0
            risk_peak = 1.0

        # C. 近窗风险腿跑输银行
        if leg == "risk" and risk_names and i >= br.underperf_window:
            window = close.index[i - br.underperf_window + 1 : i + 1]
            r_risk = rets.loc[window, risk_names].mean(axis=1)
            r_bank = bank_ret.loc[window]
            gap = float((1 + r_risk).prod() - 1) - float((1 + r_bank).prod() - 1)
            if gap <= br.underperf_gap:
                leg = "bank"
                reasons.append(f"underperf:{gap:.2%}")
                in_risk_seg = False

        # B. 单日大亏 → 当日目标仓位上限
        if day_r <= br.day_loss:
            exp = min(exp, br.day_loss_scale)
            reasons.append(f"day_loss:{day_r:.2%}")

        # 落权重
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
