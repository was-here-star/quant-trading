"""公开数据测试：连续两天三倍量后，后续 2 天上涨概率。

定义（可改参数）：
- 三倍量：当日成交量 >= 3 * 过去 N 日均量（默认 N=20，不含当日）
- 连续两天三倍量：连续两个交易日均满足三倍量
- 信号日 T：连续两天条件成立的第二日收盘
- 后 2 天收益：close[T+2] / close[T] - 1
- 上涨：后 2 天收益 > 0

数据源：yfinance（公开日线）
样本：一批流动性较好的 A 股（沪深）
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

# 沪深流动性较好的代表性个股（公开代码，便于复现）
A_SHARE_UNIVERSE = [
    # 沪市主板
    "600000.SS", "600009.SS", "600016.SS", "600019.SS", "600028.SS",
    "600030.SS", "600031.SS", "600036.SS", "600048.SS", "600050.SS",
    "600104.SS", "600111.SS", "600150.SS", "600196.SS", "600276.SS",
    "600309.SS", "600346.SS", "600406.SS", "600436.SS", "600438.SS",
    "600519.SS", "600547.SS", "600570.SS", "600585.SS", "600588.SS",
    "600690.SS", "600703.SS", "600745.SS", "600809.SS", "600887.SS",
    "600893.SS", "600900.SS", "600919.SS", "600938.SS",
    "600941.SS", "601012.SS", "601066.SS", "601088.SS", "601166.SS",
    "601211.SS", "601225.SS", "601288.SS", "601318.SS", "601328.SS",
    "601336.SS", "601398.SS", "601601.SS", "601628.SS", "601633.SS",
    "601668.SS", "601688.SS", "601728.SS", "601766.SS", "601800.SS",
    "601816.SS", "601857.SS", "601888.SS", "601899.SS", "601919.SS",
    "601985.SS", "601988.SS", "601995.SS", "603259.SS", "603288.SS",
    "603501.SS", "603799.SS", "603986.SS",
    # 深市主板 / 创业板代表
    "000001.SZ", "000002.SZ", "000063.SZ", "000100.SZ", "000157.SZ",
    "000166.SZ", "000301.SZ", "000333.SZ", "000338.SZ", "000425.SZ",
    "000538.SZ", "000568.SZ", "000596.SZ", "000625.SZ", "000651.SZ",
    "000661.SZ", "000725.SZ", "000768.SZ", "000776.SZ", "000786.SZ",
    "000858.SZ", "000876.SZ", "000895.SZ", "000938.SZ", "000977.SZ",
    "001979.SZ", "002001.SZ", "002027.SZ", "002049.SZ", "002050.SZ",
    "002142.SZ", "002179.SZ", "002230.SZ", "002236.SZ", "002241.SZ",
    "002271.SZ", "002304.SZ", "002352.SZ", "002371.SZ", "002415.SZ",
    "002460.SZ", "002466.SZ", "002475.SZ", "002594.SZ", "002714.SZ",
    "002812.SZ", "002821.SZ", "002920.SZ", "003816.SZ",
    "300015.SZ", "300059.SZ", "300122.SZ", "300124.SZ", "300142.SZ",
    "300274.SZ", "300308.SZ", "300347.SZ", "300408.SZ", "300413.SZ",
    "300433.SZ", "300450.SZ", "300498.SZ", "300750.SZ", "300759.SZ",
    "300760.SZ", "300782.SZ", "300896.SZ", "300999.SZ",
]


def download_panel(
    symbols: list[str],
    start: str,
    end: str | None,
    cache_dir: Path,
) -> dict[str, pd.DataFrame]:
    """批量下载 OHLCV，带简单 parquet 缓存。"""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, pd.DataFrame] = {}

    need = []
    for sym in symbols:
        path = cache_dir / f"{sym}_{start}_{end or 'na'}.pkl"
        if path.exists():
            df = pd.read_pickle(path)
            if not df.empty:
                out[sym] = df
                continue
        need.append(sym)

    if need:
        raw = yf.download(
            need,
            start=start,
            end=end,
            group_by="ticker",
            auto_adjust=True,
            threads=True,
            progress=False,
        )
        if len(need) == 1:
            sym = need[0]
            df = raw.copy()
            df = _normalize_ohlcv(df)
            if not df.empty:
                out[sym] = df
                df.to_pickle(cache_dir / f"{sym}_{start}_{end or 'na'}.pkl")
        else:
            for sym in need:
                try:
                    df = raw[sym].copy()
                except (KeyError, TypeError):
                    continue
                df = _normalize_ohlcv(df)
                if df.empty:
                    continue
                out[sym] = df
                df.to_pickle(cache_dir / f"{sym}_{start}_{end or 'na'}.pkl")

    return out


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    df = df.rename(
        columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df = df[cols].dropna(how="all")
    df = df[df["volume"].fillna(0) > 0]
    return df


def find_events(
    df: pd.DataFrame,
    vol_mult: float = 3.0,
    avg_window: int = 20,
    hold_days: int = 2,
) -> pd.DataFrame:
    """找出连续两天三倍量事件，并计算后续收益。"""
    x = df.copy()
    x["vol_ma"] = x["volume"].rolling(avg_window, min_periods=avg_window).mean().shift(1)
    x["is_surge"] = x["volume"] >= (vol_mult * x["vol_ma"])
    # 连续两天：今日与昨日都是三倍量
    x["signal"] = x["is_surge"] & x["is_surge"].shift(1)

    x["fwd_ret"] = x["close"].shift(-hold_days) / x["close"] - 1.0
    x["fwd_up"] = x["fwd_ret"] > 0
    # 分解：T+1、T+2 单日涨跌（相对前收）
    x["ret_d1"] = x["close"].shift(-1) / x["close"] - 1.0
    x["ret_d2"] = x["close"].shift(-2) / x["close"].shift(-1) - 1.0

    events = x.loc[x["signal"]].copy()
    events = events.dropna(subset=["fwd_ret"])
    return events[
        [
            "close",
            "volume",
            "vol_ma",
            "fwd_ret",
            "fwd_up",
            "ret_d1",
            "ret_d2",
        ]
    ]


def summarize(events: pd.DataFrame) -> dict:
    if events.empty:
        return {
            "n": 0,
            "up_prob": np.nan,
            "mean_ret": np.nan,
            "median_ret": np.nan,
            "d1_up_prob": np.nan,
            "d2_up_prob": np.nan,
            "both_up_prob": np.nan,
        }
    return {
        "n": int(len(events)),
        "up_prob": float(events["fwd_up"].mean()),
        "mean_ret": float(events["fwd_ret"].mean()),
        "median_ret": float(events["fwd_ret"].median()),
        "d1_up_prob": float((events["ret_d1"] > 0).mean()),
        "d2_up_prob": float((events["ret_d2"] > 0).mean()),
        "both_up_prob": float(((events["ret_d1"] > 0) & (events["ret_d2"] > 0)).mean()),
    }


def baseline_up_prob(panel: dict[str, pd.DataFrame], hold_days: int = 2) -> float:
    """全样本任意交易日的后 hold_days 上涨概率（对照）。"""
    rets = []
    for df in panel.values():
        r = df["close"].shift(-hold_days) / df["close"] - 1.0
        rets.append(r.dropna())
    if not rets:
        return float("nan")
    all_r = pd.concat(rets)
    return float((all_r > 0).mean())


def main() -> None:
    parser = argparse.ArgumentParser(description="连续两天三倍量后上涨概率")
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--vol-mult", type=float, default=3.0)
    parser.add_argument("--avg-window", type=int, default=20)
    parser.add_argument("--hold-days", type=int, default=2)
    parser.add_argument(
        "--cache-dir",
        default=str(Path(__file__).resolve().parents[1] / "data_cache" / "volume_surge"),
    )
    args = parser.parse_args()

    print("=" * 60)
    print("连续两天三倍量 → 后 {} 天上涨概率".format(args.hold_days))
    print(
        f"定义: 成交量 >= {args.vol_mult}x 过去{args.avg_window}日均量，连续2日；"
        f"收益=close[T+{args.hold_days}]/close[T]-1"
    )
    print(f"区间: {args.start} ~ {args.end or '最新'} | 标的数: {len(A_SHARE_UNIVERSE)}")
    print("数据源: yfinance 公开日线")
    print("=" * 60)

    panel = download_panel(
        A_SHARE_UNIVERSE,
        start=args.start,
        end=args.end,
        cache_dir=Path(args.cache_dir),
    )
    print(f"成功下载: {len(panel)} / {len(A_SHARE_UNIVERSE)} 只")

    all_events = []
    per_symbol = []
    for sym, df in panel.items():
        ev = find_events(
            df,
            vol_mult=args.vol_mult,
            avg_window=args.avg_window,
            hold_days=args.hold_days,
        )
        if ev.empty:
            continue
        ev = ev.copy()
        ev["symbol"] = sym
        all_events.append(ev)
        s = summarize(ev)
        s["symbol"] = sym
        per_symbol.append(s)

    if not all_events:
        print("未找到满足条件的事件，请放宽参数后重试。")
        return

    events = pd.concat(all_events).sort_index()
    total = summarize(events)
    base = baseline_up_prob(panel, hold_days=args.hold_days)

    print("\n【汇总】")
    print(f"事件数 n           : {total['n']}")
    print(f"后{args.hold_days}天上涨概率   : {total['up_prob']:.2%}  (对照全样本: {base:.2%})")
    print(f"后{args.hold_days}天平均收益   : {total['mean_ret']:.2%}")
    print(f"后{args.hold_days}天中位数收益 : {total['median_ret']:.2%}")
    print(f"T+1 单日上涨概率   : {total['d1_up_prob']:.2%}")
    print(f"T+2 单日上涨概率   : {total['d2_up_prob']:.2%}")
    print(f"T+1且T+2都涨概率   : {total['both_up_prob']:.2%}")

    # 分年稳定性
    events["year"] = events.index.year
    print("\n【分年】")
    print(f"{'年份':<8}{'事件数':>8}{'上涨概率':>10}{'平均收益':>10}")
    for year, g in events.groupby("year"):
        s = summarize(g)
        print(f"{year:<8}{s['n']:>8}{s['up_prob']:>9.2%}{s['mean_ret']:>9.2%}")

    # 收益分布粗分位
    q = events["fwd_ret"].quantile([0.1, 0.25, 0.5, 0.75, 0.9])
    print("\n【后2天收益分位】")
    for k, v in q.items():
        print(f"  P{int(k*100):>2}: {v:.2%}")

    # 出现次数最多的标的
    top = (
        pd.DataFrame(per_symbol)
        .sort_values("n", ascending=False)
        .head(10)
    )
    print("\n【事件最多的10只】")
    print(f"{'代码':<12}{'事件数':>6}{'上涨概率':>10}{'平均收益':>10}")
    for _, row in top.iterrows():
        print(
            f"{row['symbol']:<12}{int(row['n']):>6}"
            f"{row['up_prob']:>9.2%}{row['mean_ret']:>9.2%}"
        )

    out_csv = Path(args.cache_dir) / "events.csv"
    events.to_csv(out_csv)
    print(f"\n事件明细已保存: {out_csv}")


if __name__ == "__main__":
    main()
