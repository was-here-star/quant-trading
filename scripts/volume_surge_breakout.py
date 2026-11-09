"""近三年：连续两天三倍量 + 突破平台 → 后2天上涨概率，并输出案例。

定义：
- 三倍量：成交量 >= 3 * 过去20日均量（不含当日）
- 连续两天三倍量：连续两日均满足
- 平台：信号日前 platform_n 日（默认40），振幅 (最高-最低)/最低 <= max_range（默认25%）
- 突破：信号日收盘价 > 平台区间最高价（不含当日）
- 后2天收益：close[T+2]/close[T]-1；上涨：收益>0
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from volume_surge_prob import (
    A_SHARE_UNIVERSE,
    baseline_up_prob,
    download_panel,
    summarize,
)

# 常用代码中文名（示意用）
NAME_MAP = {
    "600519.SS": "贵州茅台",
    "300750.SZ": "宁德时代",
    "601318.SS": "中国平安",
    "000858.SZ": "五粮液",
    "002594.SZ": "比亚迪",
    "600030.SS": "中信证券",
    "000063.SZ": "中兴通讯",
    "002415.SZ": "海康威视",
    "300059.SZ": "东方财富",
    "601012.SS": "隆基绿能",
    "600276.SS": "恒瑞医药",
    "000725.SZ": "京东方A",
    "601888.SS": "中国中免",
    "002475.SZ": "立讯精密",
    "600050.SS": "中国联通",
    "600111.SS": "北方稀土",
    "600588.SS": "用友网络",
    "300450.SZ": "先导智能",
    "002230.SZ": "科大讯飞",
    "600570.SS": "恒生电子",
    "000876.SZ": "新希望",
    "601800.SS": "中国交建",
    "300413.SZ": "芒果超媒",
    "000166.SZ": "申万宏源",
    "601066.SS": "中信建投",
}


def find_events(
    df: pd.DataFrame,
    vol_mult: float = 3.0,
    avg_window: int = 20,
    platform_n: int = 40,
    max_range: float = 0.25,
    hold_days: int = 2,
) -> pd.DataFrame:
    x = df.copy()
    x["vol_ma"] = x["volume"].rolling(avg_window, min_periods=avg_window).mean().shift(1)
    x["is_surge"] = x["volume"] >= (vol_mult * x["vol_ma"])
    x["signal_vol"] = x["is_surge"] & x["is_surge"].shift(1)

    # 平台：过去 platform_n 日（不含当日）
    roll_high = x["high"].rolling(platform_n, min_periods=platform_n).max().shift(1)
    roll_low = x["low"].rolling(platform_n, min_periods=platform_n).min().shift(1)
    x["plat_high"] = roll_high
    x["plat_low"] = roll_low
    x["plat_range"] = (roll_high - roll_low) / roll_low
    x["is_platform"] = x["plat_range"] <= max_range
    x["is_breakout"] = x["close"] > x["plat_high"]

    x["signal"] = x["signal_vol"] & x["is_platform"] & x["is_breakout"]

    x["fwd_ret"] = x["close"].shift(-hold_days) / x["close"] - 1.0
    x["fwd_up"] = x["fwd_ret"] > 0
    x["ret_d1"] = x["close"].shift(-1) / x["close"] - 1.0
    x["ret_d2"] = x["close"].shift(-2) / x["close"].shift(-1) - 1.0
    x["close_t1"] = x["close"].shift(-1)
    x["close_t2"] = x["close"].shift(-2)

    cols = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "vol_ma",
        "plat_high",
        "plat_low",
        "plat_range",
        "fwd_ret",
        "fwd_up",
        "ret_d1",
        "ret_d2",
        "close_t1",
        "close_t2",
    ]
    return x.loc[x["signal"], cols].dropna(subset=["fwd_ret"])


def main() -> None:
    start_event = "2023-10-25"
    data_start = "2022-01-01"  # 预热均量/平台窗口
    root = Path(__file__).resolve().parents[1]
    cache_dir = root / "data_cache" / "volume_surge_breakout"

    print("=" * 64)
    print("连续两天三倍量 + 突破平台 → 后2天上涨概率（近三年）")
    print("三倍量: vol >= 3x 过去20日均量，连续2日")
    print("平台: 前40日振幅 <= 25%；突破: 收盘 > 平台最高价")
    print(f"事件统计区间: {start_event} ~ 最新 | 标的: {len(A_SHARE_UNIVERSE)}")
    print("=" * 64)

    panel = download_panel(
        A_SHARE_UNIVERSE,
        start=data_start,
        end=None,
        cache_dir=cache_dir,
    )
    print(f"成功下载: {len(panel)} / {len(A_SHARE_UNIVERSE)} 只")

    # 对照：近三年任意交易日
    panel_3y = {s: d.loc[d.index >= start_event] for s, d in panel.items()}
    base = baseline_up_prob(panel_3y, hold_days=2)

    all_events = []
    for sym, df in panel.items():
        ev = find_events(df)
        if ev.empty:
            continue
        ev = ev.loc[ev.index >= start_event].copy()
        if ev.empty:
            continue
        ev["symbol"] = sym
        ev["name"] = NAME_MAP.get(sym, sym.split(".")[0])
        all_events.append(ev)

    if not all_events:
        print("未找到满足条件的事件。")
        return

    events = pd.concat(all_events).sort_index()
    total = summarize(events)

    print("\n【汇总】")
    print(f"事件数 n           : {total['n']}")
    print(f"后2天上涨概率      : {total['up_prob']:.2%}  (对照全样本: {base:.2%})")
    print(f"后2天平均收益      : {total['mean_ret']:.2%}")
    print(f"后2天中位数收益    : {total['median_ret']:.2%}")
    print(f"T+1 单日上涨概率   : {total['d1_up_prob']:.2%}")
    print(f"T+2 单日上涨概率   : {total['d2_up_prob']:.2%}")
    print(f"T+1且T+2都涨概率   : {total['both_up_prob']:.2%}")

    events["year"] = events.index.year
    print("\n【分年】")
    print(f"{'年份':<8}{'事件数':>8}{'上涨概率':>10}{'平均收益':>10}")
    for year, g in events.groupby("year"):
        s = summarize(g)
        print(f"{year:<8}{s['n']:>8}{s['up_prob']:>9.2%}{s['mean_ret']:>9.2%}")

    # 案例：涨/跌各挑若干，优先知名标的
    def pick_cases(df: pd.DataFrame, n: int = 3) -> pd.DataFrame:
        known = df[df["symbol"].isin(NAME_MAP)].copy()
        pool = known if len(known) >= n else df
        # 多样性：按标的去重后取
        pool = pool.sort_values("fwd_ret", ascending=False)
        picked = []
        seen = set()
        for idx, row in pool.iterrows():
            if row["symbol"] in seen:
                continue
            seen.add(row["symbol"])
            picked.append(row)
            if len(picked) >= n:
                break
        return pd.DataFrame(picked)

    ups = events[events["fwd_up"]].copy()
    downs = events[~events["fwd_up"]].copy()
    up_cases = pick_cases(ups, 3)
    down_cases = pick_cases(downs.sort_values("fwd_ret"), 3)

    def print_cases(title: str, cases: pd.DataFrame) -> None:
        print(f"\n【{title}】")
        if cases.empty:
            print("  (无)")
            return
        for _, r in cases.iterrows():
            dt = pd.Timestamp(r.name).strftime("%Y-%m-%d")
            print(
                f"  {r['name']}({r['symbol']})  信号日 {dt}\n"
                f"    收盘 {r['close']:.2f} | 平台 [{r['plat_low']:.2f}, {r['plat_high']:.2f}]"
                f" 振幅 {r['plat_range']:.1%} | 量/均量 {r['volume']/r['vol_ma']:.1f}x\n"
                f"    T+1收 {r['close_t1']:.2f} ({r['ret_d1']:+.2%}) | "
                f"T+2收 {r['close_t2']:.2f} | 后2天 {r['fwd_ret']:+.2%}"
            )

    print_cases("上涨案例示意", up_cases)
    print_cases("下跌案例示意", down_cases)

    out_csv = cache_dir / "events_breakout_3y.csv"
    events.to_csv(out_csv)
    print(f"\n事件明细: {out_csv}")


if __name__ == "__main__":
    main()
