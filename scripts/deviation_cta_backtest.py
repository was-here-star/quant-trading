"""银行均价 vs 全A均价偏离度：选股 + 近3年回测。

框架（对应“分配权 vs 定价权”双锚）：
- 银行算术平均股价 = 政策/价值锚（分配权代理）
- 全A样本算术平均股价 = 市场β（定价权代理）
- 相对偏离度 z-score = 市场过热/过冷 → 情绪与流动性状态
- 选股：在可交易股票池中按流动性筛前 N，再按动量排序持仓
- 仓位：类 CTA —— 偏离度均值回归 + 偏离度趋势 合成方向

数据：yfinance 公开日线；样本复用 scripts/volume_surge_prob 股票池。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# 允许直接 python scripts/xxx.py 运行
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))

from volume_surge_prob import A_SHARE_UNIVERSE, download_panel
from quant.strategies.dual_anchor import DualAnchorConfig, generate_target_weights

# 银行股（分配权锚）：样本池内主要上市银行
BANK_SYMBOLS = [
    "600000.SS",  # 浦发
    "600016.SS",  # 民生
    "600036.SS",  # 招商
    "600919.SS",  # 江苏
    "601166.SS",  # 兴业
    "601288.SS",  # 农业
    "601328.SS",  # 交通
    "601398.SS",  # 工商
    "601988.SS",  # 中国银行
    "000001.SZ",  # 平安银行
    "002142.SZ",  # 宁波银行
]

NAME_HINT = {
    "600036.SS": "招商银行",
    "601318.SS": "中国平安",
    "600519.SS": "贵州茅台",
    "300750.SZ": "宁德时代",
    "002594.SZ": "比亚迪",
    "000858.SZ": "五粮液",
    "600030.SS": "中信证券",
    "300059.SZ": "东方财富",
    "002475.SZ": "立讯精密",
    "000063.SZ": "中兴通讯",
}


def build_close_panel(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """宽表收盘价，列=代码。"""
    closes = {}
    for sym, df in panel.items():
        if "close" not in df.columns or df.empty:
            continue
        s = df["close"].astype(float).copy()
        s.index = pd.to_datetime(s.index).tz_localize(None)
        closes[sym] = s
    out = pd.DataFrame(closes).sort_index()
    return out


def build_volume_panel(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    vols = {}
    for sym, df in panel.items():
        if "volume" not in df.columns or df.empty:
            continue
        s = df["volume"].astype(float).copy()
        s.index = pd.to_datetime(s.index).tz_localize(None)
        vols[sym] = s
    return pd.DataFrame(vols).sort_index()


def arithmetic_avg(close: pd.DataFrame, symbols: list[str]) -> pd.Series:
    cols = [c for c in symbols if c in close.columns]
    if not cols:
        raise ValueError("没有可用标的计算均价")
    return close[cols].mean(axis=1, skipna=True)


def compute_deviation(
    bank_avg: pd.Series,
    alla_avg: pd.Series,
    z_window: int = 60,
) -> pd.DataFrame:
    """相对偏离度及其 z-score / 动量。"""
    df = pd.DataFrame({"bank_avg": bank_avg, "alla_avg": alla_avg}).dropna()
    # 全A相对银行：>1 表示定价权相对分配权偏贵
    df["ratio"] = df["alla_avg"] / df["bank_avg"]
    df["log_ratio"] = np.log(df["ratio"])
    mu = df["log_ratio"].rolling(z_window, min_periods=z_window).mean()
    sd = df["log_ratio"].rolling(z_window, min_periods=z_window).std()
    df["z"] = (df["log_ratio"] - mu) / sd.replace(0, np.nan)
    # 偏离度趋势（CTA）：z 的 N 日变化
    df["z_mom"] = df["z"].diff(10)
    df["ratio_mom"] = df["ratio"].pct_change(20)
    return df


def regime_position(
    dev: pd.DataFrame,
    z_entry: float = 1.0,
    mode: str = "combo",
) -> pd.Series:
    """目标总仓位；A股偏多头约束下多用 [0, 1]。

    mode:
      - meanrev: 过冷做多、过热降仓（均值回归）
      - trend:   跟随偏离度趋势
      - combo:   两者合成
      - rotate:  始终满仓，用风格腿切换（见 run 内），此处返回 1
    """
    z = dev["z"]
    z_mom = dev["z_mom"]

    if mode == "meanrev":
        pos = pd.Series(0.5, index=dev.index)
        pos = pos.mask(z < -z_entry, 1.0)
        pos = pos.mask(z > z_entry, 0.0)
        pos = pos.mask((z >= -z_entry) & (z <= z_entry), 0.5)
    elif mode == "trend":
        pos = pd.Series(0.0, index=dev.index)
        pos = pos.mask(z_mom > 0, 1.0)
        pos = pos.mask(z_mom <= 0, 0.0)
    elif mode == "rotate":
        pos = pd.Series(1.0, index=dev.index)
    else:
        # combo: 过冷偏多、过热偏现金 + 弱趋势加成
        base = (-z).clip(-2, 2) / 2.0
        trend = z_mom.fillna(0).clip(-1, 1) * 0.25
        pos = (0.55 + 0.45 * base + trend).clip(0.0, 1.0)

    return pos.fillna(0.0)


def style_leg(z: pd.Series, z_entry: float = 1.0) -> pd.Series:
    """风格腿：z高(全A相对银行过热)→银行；z低→风险动量；中间→混合。

    返回 risk_weight ∈ [0,1]，银行权重 = 1 - risk_weight。
    """
    # z=-z_entry → 1.0（全仓风险腿）；z=+z_entry → 0.0（全仓银行）
    w = ((z_entry - z) / (2 * z_entry)).clip(0.0, 1.0)
    return w.fillna(0.5)


def select_holdings(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    date: pd.Timestamp,
    top_n: int,
    lookback_liq: int = 20,
    lookback_mom: int = 20,
    exclude: set[str] | None = None,
) -> list[str]:
    """在 date 当日（含）之前的信息选股：先流动性前 2N，再动量前 N。"""
    exclude = exclude or set()
    hist_c = close.loc[:date]
    hist_v = volume.loc[:date]
    if len(hist_c) < max(lookback_liq, lookback_mom) + 1:
        return []

    # 近 lookback_liq 日平均成交额代理：close * volume
    c_win = hist_c.iloc[-lookback_liq:]
    v_win = hist_v.iloc[-lookback_liq:]
    amount = (c_win * v_win).mean()
    amount = amount.dropna()
    amount = amount[[s for s in amount.index if s not in exclude]]
    if amount.empty:
        return []

    liq_pool = amount.nlargest(min(len(amount), max(top_n * 2, top_n))).index.tolist()

    # 动量：近 lookback_mom 日收益
    px = hist_c[liq_pool].iloc[-(lookback_mom + 1) :]
    if len(px) < lookback_mom + 1:
        return liq_pool[:top_n]
    mom = px.iloc[-1] / px.iloc[0] - 1.0
    mom = mom.dropna().sort_values(ascending=False)
    return mom.head(top_n).index.tolist()


def run_portfolio_backtest(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    target_exposure: pd.Series,
    top_n: int,
    rebalance: str = "W-FRI",
    fee_bps: float = 5.0,
    exclude_banks: bool = True,
    backtest_start: str | None = None,
    risk_weight: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """等权持仓 top_n，总仓位跟随 target_exposure；T 日收盘调仓，T+1 生效。

    若提供 risk_weight：组合 = risk_weight * 动量池 + (1-risk_weight) * 银行等权。
    """
    exclude = set(BANK_SYMBOLS) if exclude_banks else set()
    bank_cols = [c for c in BANK_SYMBOLS if c in close.columns]
    rebal_dates = close.resample(rebalance).last().dropna(how="all").index
    rebal_dates = close.index.intersection(rebal_dates)

    if backtest_start:
        start_ts = pd.Timestamp(backtest_start)
        close = close.loc[close.index >= start_ts]
        volume = volume.loc[volume.index >= start_ts]
        target_exposure = target_exposure.reindex(close.index).ffill().fillna(0.0)
        if risk_weight is not None:
            risk_weight = risk_weight.reindex(close.index).ffill().fillna(0.5)
        rebal_dates = rebal_dates[rebal_dates >= start_ts]

    dates = close.index
    weights = pd.DataFrame(0.0, index=dates, columns=close.columns)
    holdings_log: list[dict] = []

    last_picks: list[str] = []
    for i, dt in enumerate(dates):
        if dt in rebal_dates or i == 0:
            picks = select_holdings(
                close, volume, dt, top_n=top_n, exclude=exclude
            )
            if picks:
                last_picks = picks
            rw = float(risk_weight.loc[dt]) if risk_weight is not None else 1.0
            holdings_log.append(
                {
                    "date": dt,
                    "n": len(last_picks),
                    "symbols": ",".join(last_picks),
                    "exposure": float(target_exposure.get(dt, 0.0)),
                    "risk_weight": rw,
                }
            )

        if not last_picks and risk_weight is None:
            continue
        exp = float(target_exposure.get(dt, 0.0))
        if risk_weight is None:
            rw, bw = 1.0, 0.0
        else:
            rw = float(risk_weight.loc[dt])
            bw = 1.0 - rw

        if last_picks and rw > 0:
            w_risk = exp * rw / len(last_picks)
            for s in last_picks:
                if s in weights.columns:
                    weights.at[dt, s] = w_risk
        if bank_cols and bw > 0:
            w_bank = exp * bw / len(bank_cols)
            for s in bank_cols:
                weights.at[dt, s] = w_bank

    w_exec = weights.shift(1).fillna(0.0)
    rets = close.pct_change(fill_method=None).fillna(0.0)
    port_ret = (w_exec * rets).sum(axis=1)

    turnover = w_exec.diff().abs().sum(axis=1).fillna(0.0)
    fee = turnover * (fee_bps / 10_000.0)
    net_ret = port_ret - fee

    ew = close.pct_change(fill_method=None).mean(axis=1).fillna(0.0)
    bank_ew = close[bank_cols].pct_change(fill_method=None).mean(axis=1).fillna(0.0)

    result = pd.DataFrame(
        {
            "strategy": net_ret,
            "gross": port_ret,
            "turnover": turnover,
            "exposure": target_exposure.reindex(dates).ffill().fillna(0.0),
            "bench_ew": ew,
            "bench_bank": bank_ew,
        },
        index=dates,
    )
    hold_df = pd.DataFrame(holdings_log)
    return result, hold_df


def perf_stats(ret: pd.Series) -> dict[str, float]:
    ret = ret.dropna()
    if ret.empty:
        return {
            "total_return": np.nan,
            "ann_return": np.nan,
            "ann_vol": np.nan,
            "sharpe": np.nan,
            "max_drawdown": np.nan,
            "win_rate": np.nan,
        }
    equity = (1.0 + ret).cumprod()
    total = float(equity.iloc[-1] - 1.0)
    n = len(ret)
    ann = float(equity.iloc[-1] ** (252 / max(n, 1)) - 1.0) if n > 0 else np.nan
    vol = float(ret.std() * np.sqrt(252))
    sharpe = float(ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0.0
    dd = float((equity / equity.cummax() - 1.0).min())
    win = float((ret > 0).mean())
    return {
        "total_return": total,
        "ann_return": ann,
        "ann_vol": vol,
        "sharpe": sharpe,
        "max_drawdown": dd,
        "win_rate": win,
    }


def print_stats(name: str, s: dict[str, float]) -> None:
    print(
        f"{name:<16}"
        f"{s['total_return']:>10.2%}"
        f"{s['ann_return']:>10.2%}"
        f"{s['ann_vol']:>10.2%}"
        f"{s['sharpe']:>8.2f}"
        f"{s['max_drawdown']:>10.2%}"
        f"{s['win_rate']:>8.2%}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="偏离度 CTA 选股回测")
    parser.add_argument("--start", default="2022-01-01", help="下载起始（含预热）")
    parser.add_argument("--end", default=None)
    parser.add_argument("--bt-start", default="2023-10-30", help="回测起始（近3年）")
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--z-window", type=int, default=60)
    parser.add_argument("--z-entry", type=float, default=1.0)
    parser.add_argument(
        "--mode",
        default="apply",
        choices=["apply", "meanrev", "trend", "combo", "rotate", "all"],
        help="apply=可应用主策略（双腿CTA）；all=对比旧实验",
    )
    parser.add_argument("--rebalance", default="W-FRI", help="调仓频率")
    parser.add_argument("--fee-bps", type=float, default=5.0)
    parser.add_argument(
        "--cache-dir",
        default=str(
            Path(__file__).resolve().parents[1] / "data_cache" / "deviation_cta"
        ),
    )
    parser.add_argument("--compare-n", default="10,50", help="对比持仓数量，逗号分隔")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("银行均价 vs 全A均价偏离度 | 类CTA选股回测")
    print(f"下载区间: {args.start} ~ {args.end or '最新'}")
    print(f"回测区间: {args.bt_start} ~ {args.end or '最新'}（近3年）")
    print(
        f"参数: z_window={args.z_window}, mode={args.mode}, "
        f"rebalance={args.rebalance}, fee={args.fee_bps}bp"
    )
    print(f"股票池: {len(A_SHARE_UNIVERSE)} | 银行锚: {len(BANK_SYMBOLS)}")
    print("=" * 72)

    panel = download_panel(
        A_SHARE_UNIVERSE,
        start=args.start,
        end=args.end,
        cache_dir=cache_dir,
    )
    print(f"成功加载: {len(panel)} / {len(A_SHARE_UNIVERSE)}")

    close = build_close_panel(panel)
    volume = build_volume_panel(panel).reindex(close.index).fillna(0.0)

    bank_avg = arithmetic_avg(close, BANK_SYMBOLS)
    alla_avg = arithmetic_avg(close, list(close.columns))
    dev = compute_deviation(bank_avg, alla_avg, z_window=args.z_window)

    # 对齐
    common = close.index.intersection(dev.index)
    close = close.loc[common]
    volume = volume.loc[common]
    dev = dev.loc[common]

    print("\n【双锚指数摘要】")
    print(
        f"银行均价末值: {dev['bank_avg'].iloc[-1]:.2f} | "
        f"全A均价末值: {dev['alla_avg'].iloc[-1]:.2f} | "
        f"ratio末值: {dev['ratio'].iloc[-1]:.3f} | "
        f"z末值: {dev['z'].iloc[-1]:.2f}"
    )

    # 保存偏离度序列
    dev_path = cache_dir / "deviation_series.csv"
    dev.to_csv(dev_path)
    print(f"偏离度序列: {dev_path}")

    top_list = [int(x) for x in args.compare_n.split(",") if x.strip()]
    header = (
        f"{'方案':<16}{'累计收益':>10}{'年化':>10}{'波动':>10}"
        f"{'夏普':>8}{'最大回撤':>10}{'胜率':>8}"
    )
    print("\n" + header)
    print("-" * len(header))

    equity_store: dict[str, pd.Series] = {}
    all_holdings: dict[str, pd.DataFrame] = {}
    main_tag: str | None = None

    if args.mode == "apply":
        # 可应用主策略：比价趋势双腿切换 + 极端偏离降仓
        for n in top_list:
            cfg = DualAnchorConfig(
                z_window=args.z_window,
                top_n=n,
                rebalance=args.rebalance,
            )
            w, state = generate_target_weights(
                close, volume, cfg=cfg, bank_symbols=BANK_SYMBOLS
            )
            w_bt = w.loc[w.index >= pd.Timestamp(args.bt_start)]
            c_bt = close.loc[close.index >= pd.Timestamp(args.bt_start)]
            w_exec = w_bt.shift(1).fillna(0.0)
            rets = c_bt.pct_change(fill_method=None).fillna(0.0)
            gross = (w_exec * rets).sum(axis=1)
            fee = w_exec.diff().abs().sum(axis=1).fillna(0.0) * (args.fee_bps / 10_000.0)
            net = gross - fee
            tag = f"apply_top{n}"
            st = perf_stats(net)
            print_stats(tag, st)
            equity_store[tag] = (1.0 + net).cumprod()
            holds = state.loc[state.index >= pd.Timestamp(args.bt_start)].copy()
            holds = holds.reset_index()
            all_holdings[tag] = holds
            pd.DataFrame({"strategy": net}).to_csv(cache_dir / f"returns_{tag}.csv")
            holds.to_csv(cache_dir / f"holdings_{tag}.csv", index=False)
            if main_tag is None:
                main_tag = tag
    else:
        if args.mode == "all":
            modes = ["meanrev", "trend", "combo", "rotate"]
        else:
            modes = [args.mode]
        for mode in modes:
            exposure = regime_position(dev, z_entry=args.z_entry, mode=mode)
            rw = style_leg(dev["z"], z_entry=args.z_entry) if mode == "rotate" else None
            for n in top_list:
                tag = f"{mode}_top{n}"
                res, holds = run_portfolio_backtest(
                    close,
                    volume,
                    target_exposure=exposure,
                    top_n=n,
                    rebalance=args.rebalance,
                    fee_bps=args.fee_bps,
                    exclude_banks=True,
                    backtest_start=args.bt_start,
                    risk_weight=rw,
                )
                res = res.loc[res.index >= pd.Timestamp(args.bt_start)]
                st = perf_stats(res["strategy"])
                print_stats(tag, st)
                equity_store[tag] = (1.0 + res["strategy"]).cumprod()
                all_holdings[tag] = holds
                res.to_csv(cache_dir / f"returns_{tag}.csv")
                holds.to_csv(cache_dir / f"holdings_{tag}.csv", index=False)

    # 基准（同区间）
    bt_close = close.loc[close.index >= pd.Timestamp(args.bt_start)]
    bench_ew = bt_close.pct_change(fill_method=None).mean(axis=1).fillna(0.0)
    bank_cols = [c for c in BANK_SYMBOLS if c in bt_close.columns]
    bench_bank = bt_close[bank_cols].pct_change(fill_method=None).mean(axis=1).fillna(0.0)
    print_stats("bench_全A等权", perf_stats(bench_ew))
    print_stats("bench_银行等权", perf_stats(bench_bank))
    equity_store["bench_全A等权"] = (1.0 + bench_ew).cumprod()
    equity_store["bench_银行等权"] = (1.0 + bench_bank).cumprod()

    # 最近一期持仓
    if main_tag is None:
        preferred = [
            f"apply_top{top_list[0]}",
            f"rotate_top{top_list[0]}",
            f"combo_top{top_list[0]}",
            f"{args.mode}_top{top_list[0]}",
        ]
        main_tag = next((t for t in preferred if t in all_holdings), None)
    if main_tag and not all_holdings[main_tag].empty:
        last = all_holdings[main_tag].iloc[-1]
        if "leg" in last.index:
            print(
                f"\n【最近调仓 {main_tag}】{pd.Timestamp(last['date']).date()} "
                f"腿={last['leg']} 仓位={float(last['exposure']):.2f} z={float(last['z']):.2f}"
            )
            syms = str(last.get("risk_names", "")).split(",") if last.get("risk_names") else []
            if last["leg"] == "bank":
                print("  → 银行等权腿（分配权）")
            for s in syms:
                if s:
                    print(f"  {s:<12} {NAME_HINT.get(s, '')}")
        else:
            rw = last.get("risk_weight", 1.0)
            print(
                f"\n【最近调仓 {main_tag}】{pd.Timestamp(last['date']).date()} "
                f"仓位={last['exposure']:.2f} 风险腿={float(rw):.2f}"
            )
            syms = str(last["symbols"]).split(",") if last.get("symbols") else []
            for s in syms:
                print(f"  {s:<12} {NAME_HINT.get(s, '')}")

    # 净值曲线（英文标题，避免缺字库）
    fig, axes = plt.subplots(
        2, 1, figsize=(11, 7), sharex=False, gridspec_kw={"height_ratios": [2, 1]}
    )
    ax0, ax1 = axes
    for name, eq in equity_store.items():
        style = "--" if name.startswith("bench") else "-"
        ax0.plot(eq.index, eq.values, style, label=name, linewidth=1.2)
    ax0.set_title("Equity Curve (start=1), ~3Y A-share")
    ax0.legend(fontsize=8, loc="upper left")
    ax0.grid(True, alpha=0.3)

    bt_dev = dev.loc[dev.index >= pd.Timestamp(args.bt_start)]
    ax1.plot(bt_dev.index, bt_dev["z"], color="tab:purple", label="z-score")
    ax1.axhline(args.z_entry, color="r", ls="--", lw=0.8, label="+entry")
    ax1.axhline(-args.z_entry, color="g", ls="--", lw=0.8, label="-entry")
    ax1.axhline(0, color="gray", ls=":", lw=0.8)
    ax1.set_title("AllA / Bank log-ratio z-score (hot>0 / cold<0)")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    fig.tight_layout()
    fig_path = cache_dir / "equity_deviation_cta.png"
    fig.savefig(fig_path, dpi=140)
    print(f"\n净值图: {fig_path}")
    print("完成。")


if __name__ == "__main__":
    main()
