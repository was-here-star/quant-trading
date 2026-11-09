"""公开数据：穿透形态（刺透形态）后第1天、第2天上涨概率。

经典定义（信号日 T = 阳线刺透日）：
1. T-1 为阴线（close < open），实体相对充分
2. T 为阳线（close > open）
3. T 开盘低于 T-1 收盘（A股常见放宽；严格版要求开盘 < T-1最低价）
4. T 收盘刺入 T-1 实体一半以上：close_T > (open_{T-1}+close_{T-1})/2
5. T 收盘仍低于 T-1 开盘（未完全吞没，否则偏看涨吞没）
6. 可选：短期下跌背景（近5日收盘下行）

后第1天 / 第2天：相对各自前收的单日涨跌。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from volume_surge_prob import A_SHARE_UNIVERSE, download_panel


def find_piercing(
    df: pd.DataFrame,
    *,
    min_body_ratio: float = 0.5,
    require_downtrend: bool = True,
    strict_gap: bool = False,
) -> pd.DataFrame:
    x = df.copy()
    o, h, l, c = x["open"], x["high"], x["low"], x["close"]
    rng = (h - l).replace(0, np.nan)

    body = (c - o).abs()
    body_ratio = body / rng

    prev_o, prev_c, prev_l = o.shift(1), c.shift(1), l.shift(1)
    prev_mid = (prev_o + prev_c) / 2.0
    prev_bear = prev_c < prev_o
    prev_long = (body.shift(1) / rng.shift(1)) >= min_body_ratio

    cur_bull = c > o
    cur_body_ok = body_ratio >= min_body_ratio

    if strict_gap:
        gap_ok = o < prev_l
    else:
        gap_ok = o < prev_c

    pierce = c > prev_mid
    not_engulf = c < prev_o

    signal = prev_bear & prev_long & cur_bull & cur_body_ok & gap_ok & pierce & not_engulf

    if require_downtrend:
        # 近5日收盘整体下行：今日前一日收盘低于5日前收盘
        downtrend = prev_c < c.shift(6)
        signal = signal & downtrend

    x["signal"] = signal.fillna(False)
    x["ret_d1"] = c.shift(-1) / c - 1.0
    x["ret_d2"] = c.shift(-2) / c.shift(-1) - 1.0
    x["close_t1"] = c.shift(-1)
    x["close_t2"] = c.shift(-2)
    x["prev_open"] = prev_o
    x["prev_close"] = prev_c
    x["prev_mid"] = prev_mid

    cols = [
        "open",
        "high",
        "low",
        "close",
        "prev_open",
        "prev_close",
        "prev_mid",
        "ret_d1",
        "ret_d2",
        "close_t1",
        "close_t2",
    ]
    return x.loc[x["signal"], cols].dropna(subset=["ret_d1", "ret_d2"])


def day_baseline(panel: dict[str, pd.DataFrame]) -> tuple[float, float]:
    """任意交易日的次日、再次日单日上涨概率。"""
    d1, d2 = [], []
    for df in panel.values():
        r1 = (df["close"].shift(-1) / df["close"] - 1.0).dropna()
        r2 = (df["close"].shift(-2) / df["close"].shift(-1) - 1.0).dropna()
        d1.append(r1)
        d2.append(r2)
    a = pd.concat(d1)
    b = pd.concat(d2)
    return float((a > 0).mean()), float((b > 0).mean())


def report(title: str, events: pd.DataFrame, base_d1: float, base_d2: float) -> None:
    n = len(events)
    d1_up = float((events["ret_d1"] > 0).mean()) if n else np.nan
    d2_up = float((events["ret_d2"] > 0).mean()) if n else np.nan
    both = float(((events["ret_d1"] > 0) & (events["ret_d2"] > 0)).mean()) if n else np.nan
    print(f"\n【{title}】")
    print(f"事件数              : {n}")
    print(f"后第1天上涨概率     : {d1_up:.2%}  (对照: {base_d1:.2%})")
    print(f"后第2天上涨概率     : {d2_up:.2%}  (对照: {base_d2:.2%})")
    print(f"两天都涨概率        : {both:.2%}")
    if n:
        print(f"第1天平均收益       : {events['ret_d1'].mean():.2%}  中位: {events['ret_d1'].median():.2%}")
        print(f"第2天平均收益       : {events['ret_d2'].mean():.2%}  中位: {events['ret_d2'].median():.2%}")


def pick_examples(events: pd.DataFrame, n: int = 3) -> None:
    if events.empty:
        return
    print("\n【案例示意】")
    # 分散标的：按 |ret_d1| 选涨跌各若干
    ups = events[events["ret_d1"] > 0].sort_values("ret_d1", ascending=False)
    dns = events[events["ret_d1"] <= 0].sort_values("ret_d1")
    shown = set()
    rows = []
    for pool in (ups, dns):
        for idx, r in pool.iterrows():
            if r["symbol"] in shown:
                continue
            shown.add(r["symbol"])
            rows.append((idx, r))
            if len([x for x in rows if (x[1]["ret_d1"] > 0) == (r["ret_d1"] > 0)]) >= n:
                break
    for idx, r in rows[: n * 2]:
        dt = pd.Timestamp(idx).strftime("%Y-%m-%d")
        print(
            f"  {r['symbol']} 信号日 {dt} | "
            f"T-1收 {r['prev_close']:.2f}→中点 {r['prev_mid']:.2f} | "
            f"T开 {r['open']:.2f} 收 {r['close']:.2f} | "
            f"D1 {r['ret_d1']:+.2%}  D2 {r['ret_d2']:+.2%}"
        )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    cache_dir = root / "data_cache" / "piercing"
    start = "2018-01-01"

    print("=" * 64)
    print("穿透形态（刺透）→ 后第1天 / 第2天上涨概率")
    print("数据: yfinance 公开日线 | 样本: 流动性较好的A股")
    print(f"区间: {start} ~ 最新 | 标的数: {len(A_SHARE_UNIVERSE)}")
    print("=" * 64)

    panel = download_panel(A_SHARE_UNIVERSE, start=start, end=None, cache_dir=cache_dir)
    print(f"成功下载: {len(panel)} / {len(A_SHARE_UNIVERSE)} 只")

    base_d1, base_d2 = day_baseline(panel)

    configs = [
        ("全样本·A股常用（低开+刺透+下跌背景）", False, True, None),
        ("全样本·严格跳空（开盘<昨低）", True, True, None),
        ("近三年·A股常用", False, True, "2023-10-25"),
    ]

    all_for_csv = []
    for title, strict_gap, require_downtrend, since in configs:
        events = []
        for sym, df in panel.items():
            ev = find_piercing(
                df, strict_gap=strict_gap, require_downtrend=require_downtrend
            )
            if ev.empty:
                continue
            if since:
                ev = ev.loc[ev.index >= since]
            if ev.empty:
                continue
            ev = ev.copy()
            ev["symbol"] = sym
            events.append(ev)
        if not events:
            print(f"\n【{title}】无事件")
            continue
        e = pd.concat(events).sort_index()
        if since:
            sub = {s: d.loc[d.index >= since] for s, d in panel.items()}
            b1, b2 = day_baseline(sub)
        else:
            b1, b2 = base_d1, base_d2
        report(title, e, b1, b2)
        pick_examples(e, n=2 if since is None else 3)
        all_for_csv.append(e.assign(rule=title))

        e2 = e.copy()
        e2["year"] = e2.index.year
        parts = [
            f"{y} n={len(g)} D1={(g['ret_d1']>0).mean():.0%} D2={(g['ret_d2']>0).mean():.0%}"
            for y, g in e2.groupby("year")
        ]
        print("  分年: " + " | ".join(parts))

    if all_for_csv:
        out = cache_dir / "piercing_events.csv"
        pd.concat(all_for_csv).to_csv(out)
        print(f"\n事件明细: {out}")


if __name__ == "__main__":
    main()
