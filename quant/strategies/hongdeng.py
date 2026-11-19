"""红灯策略：指定红升级版——银行腿改为「价值腿」轮动。

相对「指定红策略」的核心改动
----------------------------
指定红：trend ≤ 0 → 100% 银行腿（银行等权）
红灯：  trend ≤ 0 → 价值腿：
       · 50% 银行腿（银行等权）
       · 50% 由六大价值方向中近窗收益最高的两者平分（各 25%，方向内等权）

价值方向（可扩展）
----------------
银行、煤炭、保险、白酒、电力、证券、石油化工、地产

其余规则与指定红一致
--------------------
1. ratio = 全A均价 / 银行均价（锚点仍用银行，保持分配权语义）
2. z = zscore(log(ratio), 60)
3. 月末：trend > 0 → 100% 风险腿（流动性前 2N → 动量前 N）
4. 月末：trend ≤ 0 → 价值腿（50%银行 + 候选方向近窗 TopK）
5. 月末：|z| > 2 → 总仓位 × 0.5
6. 非月末：沿用上月末持仓；T+1 生效
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from quant.strategies.dual_anchor import (
    DEFAULT_BANKS,
    DualAnchorConfig,
    build_anchors,
    select_risk_names,
)


STRATEGY_ID = "hongdeng"
STRATEGY_NAME = "红灯策略"
STRATEGY_CODE = "hongdeng"


# 八大价值方向池（均落在现有 A_SHARE_UNIVERSE 内）
# 银行 / 煤炭 / 保险 / 白酒 / 电力 / 证券 / 石油化工 / 地产
DEFAULT_VALUE_SECTORS: dict[str, list[str]] = {
    "银行": list(DEFAULT_BANKS),
    "煤炭": ["601088.SS", "601225.SS"],
    "保险": ["601318.SS", "601336.SS", "601601.SS", "601628.SS"],
    "白酒": [
        "600519.SS",
        "600809.SS",
        "000568.SZ",
        "000596.SZ",
        "000858.SZ",
        "002304.SZ",
    ],
    "电力": ["600900.SS", "601985.SS", "003816.SZ"],
    "证券": [
        "600030.SS",
        "601066.SS",
        "601211.SS",
        "601688.SS",
        "601995.SS",
        "000166.SZ",
        "000776.SZ",
        "300059.SZ",
    ],
    "石油化工": [
        "600028.SS",  # 中国石化
        "601857.SS",  # 中国石油
        "600346.SS",  # 恒力石化
        "600309.SS",  # 万华化学
    ],
    "地产": [
        "000002.SZ",  # 万科A
        "600048.SS",  # 保利发展
        "001979.SZ",  # 招商蛇口
    ],
}


@dataclass
class HongdengConfig(DualAnchorConfig):
    """红灯策略参数；继承双锚默认，并增加价值腿轮动窗。"""

    # 价值方向相对强弱回看天数（与 trend 默认同窗，便于解释）
    value_lookback: int = 20
    # 价值腿：固定银行占比 + 六方向 TopK 分配剩余
    value_bank_share: float = 0.5
    value_top_k: int = 2
    # TopK 相对权重，如 (3, 2)；None=等权。长度可短于实际可用数，按序截取后归一化
    value_top_ratios: tuple[float, ...] | None = None
    value_sectors: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_VALUE_SECTORS.items()}
    )


def _sector_available(close: pd.DataFrame, symbols: list[str]) -> list[str]:
    return [s for s in symbols if s in close.columns]


def score_value_sectors(
    close: pd.DataFrame,
    date: pd.Timestamp,
    sectors: dict[str, list[str]],
    lookback: int = 20,
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """计算各价值方向等权近 lookback 收益，及可用成分。"""
    hist = close.loc[:date]
    scores: dict[str, float] = {}
    members: dict[str, list[str]] = {}
    need = lookback + 1
    if len(hist) < need:
        for name, syms in sectors.items():
            members[name] = _sector_available(close, syms)
        return scores, members

    for name, syms in sectors.items():
        cols = _sector_available(close, syms)
        members[name] = cols
        if len(cols) < 1:
            continue
        px = hist[cols].iloc[-(lookback + 1) :]
        if len(px) < lookback + 1:
            continue
        # 等权组合收益：先各股收益再平均，避免价格水平偏差
        rets = (px.iloc[-1] / px.iloc[0] - 1.0).replace([np.inf, -np.inf], np.nan).dropna()
        if rets.empty:
            continue
        scores[name] = float(rets.mean())
    return scores, members


def pick_value_sector(
    close: pd.DataFrame,
    date: pd.Timestamp,
    sectors: dict[str, list[str]],
    lookback: int = 20,
) -> tuple[str, list[str], dict[str, float]]:
    """兼容旧接口：返回单一占优方向。"""
    names, members_map, scores = pick_value_sectors_top_k(
        close, date, sectors, lookback=lookback, top_k=1
    )
    best = names[0] if names else "银行"
    return best, members_map.get(best, []), scores


def pick_value_sectors_top_k(
    close: pd.DataFrame,
    date: pd.Timestamp,
    sectors: dict[str, list[str]],
    lookback: int = 20,
    top_k: int = 2,
) -> tuple[list[str], dict[str, list[str]], dict[str, float]]:
    """按等权近 lookback 收益选取前 top_k 个价值方向。

    Returns:
        ranked_names, members_by_sector, sector_returns
    """
    scores, members = score_value_sectors(close, date, sectors, lookback=lookback)
    banks = members.get("银行") or _sector_available(
        close, sectors.get("银行", list(DEFAULT_BANKS))
    )
    if not scores:
        return (["银行"] if banks else []), members, scores

    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    names: list[str] = []
    for name, _ in ranked:
        picks = members.get(name) or []
        if not picks:
            continue
        names.append(name)
        if len(names) >= max(1, int(top_k)):
            break
    if not names:
        return (["银行"] if banks else []), members, scores
    return names, members, scores


def all_value_symbols(sectors: dict[str, list[str]] | None = None) -> set[str]:
    secs = sectors or DEFAULT_VALUE_SECTORS
    out: set[str] = set()
    for syms in secs.values():
        out.update(syms)
    return out


def _normalize_top_ratios(
    n: int, ratios: tuple[float, ...] | list[float] | None
) -> list[float]:
    """把 TopK 相对比例归一化为长度 n 的权重；ratios 为空则等权。"""
    if n <= 0:
        return []
    if not ratios:
        return [1.0 / n] * n
    vals = [float(x) for x in list(ratios)[:n]]
    while len(vals) < n:
        vals.append(vals[-1] if vals else 1.0)
    vals = [max(0.0, v) for v in vals]
    s = sum(vals)
    if s <= 0:
        return [1.0 / n] * n
    return [v / s for v in vals]


def _allocate_value_leg(
    columns: pd.Index,
    bank_cols: list[str],
    top_names: list[str],
    members: dict[str, list[str]],
    *,
    exposure: float,
    bank_share: float,
    top_ratios: tuple[float, ...] | list[float] | None = None,
) -> tuple[pd.Series, list[str], str]:
    """价值腿权重：bank_share 给银行等权，剩余按 TopK 比例分配。"""
    raw = pd.Series(0.0, index=columns)
    held: list[str] = []
    bank_share = float(np.clip(bank_share, 0.0, 1.0))
    sat_share = 1.0 - bank_share

    if bank_cols and bank_share > 0:
        w_bank = exposure * bank_share / len(bank_cols)
        for s in bank_cols:
            if s in raw.index:
                raw.at[s] += w_bank
                held.append(s)

    usable = [n for n in top_names if members.get(n)]
    sector_w: list[float] = []
    if usable and sat_share > 0:
        sector_w = _normalize_top_ratios(len(usable), top_ratios)
        for name, share in zip(usable, sector_w):
            cols = members[name]
            w = exposure * sat_share * share / len(cols)
            for s in cols:
                if s in raw.index:
                    raw.at[s] += w
                    held.append(s)

    # 极端兜底：仅银行
    if raw.sum() <= 1e-12 and bank_cols:
        w = exposure / len(bank_cols)
        for s in bank_cols:
            raw.at[s] = w
        held = list(bank_cols)
        label = "银行100%"
    else:
        bank_pct = int(round(100 * bank_share))
        if not usable:
            label = f"银行{bank_pct}%"
        elif len(usable) == 1:
            sat_pct = int(round(100 * sat_share))
            label = f"银行{bank_pct}%+{usable[0]}{sat_pct}%"
        else:
            parts = []
            for name, share in zip(usable, sector_w):
                parts.append(f"{name}{int(round(100 * sat_share * share))}%")
            label = f"银行{bank_pct}%+{'+'.join(parts)}"

    # 保序去重
    seen: set[str] = set()
    uniq: list[str] = []
    for s in held:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return raw, uniq, label


def generate_target_weights_hongdeng(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    cfg: HongdengConfig | None = None,
    bank_symbols: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成红灯策略目标权重（收盘决策）；回测请 shift(1) 作 T+1。"""
    cfg = cfg or HongdengConfig()
    banks = bank_symbols or DEFAULT_BANKS
    bank_cols = [c for c in banks if c in close.columns]
    # 风险腿选股时排除全部价值池，避免与价值腿重叠
    exclude = all_value_symbols(cfg.value_sectors) | set(bank_cols)

    anchors = build_anchors(
        close,
        banks,
        z_window=cfg.z_window,
        trend_lookback=cfg.trend_lookback,
    )

    try:
        rebal_dates = close.resample(cfg.rebalance).last().dropna(how="all").index
    except ValueError:
        alt = {"BME": "BM", "ME": "M"}.get(cfg.rebalance, cfg.rebalance)
        rebal_dates = close.resample(alt).last().dropna(how="all").index
    rebal_dates = set(close.index.intersection(rebal_dates))

    weights = pd.DataFrame(0.0, index=close.index, columns=close.columns)
    rows: list[dict] = []
    last_risk: list[str] = []
    last_value: list[str] = []
    held_leg = "value"
    held_sector = "银行50%"
    held_exp = 1.0
    prev_w = pd.Series(0.0, index=close.columns)
    last_scores: dict[str, float] = {}

    for i, dt in enumerate(close.index):
        z = float(anchors.at[dt, "z"]) if pd.notna(anchors.at[dt, "z"]) else 0.0
        tr = float(anchors.at[dt, "trend"]) if pd.notna(anchors.at[dt, "trend"]) else 0.0
        is_rebal = dt in rebal_dates or i == 0
        signal_leg = "risk" if tr > 0 else "value"

        if is_rebal:
            held_exp = cfg.crisis_scale if abs(z) > cfg.z_crisis else 1.0
            if tr > 0:
                held_leg = "risk"
                held_sector = ""
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
                if last_risk:
                    w = held_exp / len(last_risk)
                    for s in last_risk:
                        if s in raw.index:
                            raw.at[s] = w
                prev_w = raw
            else:
                held_leg = "value"
                top_names, members, scores = pick_value_sectors_top_k(
                    close,
                    dt,
                    cfg.value_sectors,
                    lookback=cfg.value_lookback,
                    top_k=cfg.value_top_k,
                )
                last_scores = scores
                raw, last_value, held_sector = _allocate_value_leg(
                    close.columns,
                    bank_cols,
                    top_names,
                    members,
                    exposure=held_exp,
                    bank_share=cfg.value_bank_share,
                    top_ratios=cfg.value_top_ratios,
                )
                prev_w = raw

        weights.loc[dt] = prev_w.to_numpy()
        score_txt = ""
        if last_scores:
            # 记录当次/最近一次价值方向得分，便于信号打印
            score_txt = ";".join(
                f"{k}:{v:+.2%}" for k, v in sorted(last_scores.items(), key=lambda x: -x[1])
            )

        rows.append(
            {
                "date": dt,
                "z": z,
                "trend": tr,
                "leg": held_leg,
                "value_sector": held_sector if held_leg == "value" else "",
                "exposure": held_exp,
                "rebalance": bool(is_rebal),
                "signal_leg": signal_leg,
                "risk_names": ",".join(last_risk) if held_leg == "risk" else "",
                "value_names": ",".join(last_value) if held_leg == "value" else "",
                "value_scores": score_txt if held_leg == "value" else "",
                # 看板圆环：价值腿整块计入「价值腿/银行腿」色，细节见 value_sector
                "bank_weight": held_exp if held_leg in ("value", "bank") else 0.0,
                "risk_weight": held_exp if held_leg == "risk" else 0.0,
            }
        )

    state = pd.DataFrame(rows).set_index("date")
    return weights, state
