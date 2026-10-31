"""策略1 应用入口：今日信号 / 持仓分布 / 回测 / 熔断对比。

用法:
  python scripts/strategy1.py signal
  python scripts/strategy1.py signal --breaker          # 启用 A+B+C 熔断
  python scripts/strategy1.py backtest --breaker
  python scripts/strategy1.py compare-breaker           # 2026至今 原版 vs 熔断
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from volume_surge_prob import A_SHARE_UNIVERSE, download_panel

from quant.strategies.strategy1 import (
    STRATEGY_BREAKER_NAME,
    STRATEGY_ID,
    STRATEGY_NAME,
    BreakerConfig,
    Strategy1Config,
    build_anchors,
    generate_target_weights,
    generate_target_weights_breaker,
)

BANK_NAMES = {
    "600000.SS": "浦发银行",
    "600016.SS": "民生银行",
    "600036.SS": "招商银行",
    "600919.SS": "江苏银行",
    "601166.SS": "兴业银行",
    "601288.SS": "农业银行",
    "601328.SS": "交通银行",
    "601398.SS": "工商银行",
    "601988.SS": "中国银行",
    "000001.SZ": "平安银行",
    "002142.SZ": "宁波银行",
}

NAME_HINT = {
    **BANK_NAMES,
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


def _panels(start: str, cache_dir: Path):
    from deviation_cta_backtest import (
        BANK_SYMBOLS,
        build_close_panel,
        build_volume_panel,
        perf_stats,
        print_stats,
    )

    panel = download_panel(
        A_SHARE_UNIVERSE, start=start, end=None, cache_dir=cache_dir
    )
    close = build_close_panel(panel)
    volume = build_volume_panel(panel).reindex(close.index).fillna(0.0)
    return close, volume, BANK_SYMBOLS, perf_stats, print_stats


def cmd_signal(args: argparse.Namespace) -> int:
    cache = ROOT / "data_cache" / "strategy1"
    close, volume, banks, _, _ = _panels(args.start, cache)

    anchors = build_anchors(close, banks, z_window=60, trend_lookback=20)
    last = anchors.dropna(subset=["trend"]).iloc[-1]
    dt = anchors.dropna(subset=["trend"]).index[-1]
    direction = "向上" if last["trend"] > 0 else "向下"

    cfg = Strategy1Config(top_n=args.top_n)
    if args.breaker:
        w, state = generate_target_weights_breaker(
            close, volume, cfg=cfg, breaker=BreakerConfig(), bank_symbols=banks
        )
        tag = STRATEGY_BREAKER_NAME
    else:
        w, state = generate_target_weights(close, volume, cfg=cfg, bank_symbols=banks)
        tag = f"策略{STRATEGY_ID}｜{STRATEGY_NAME}"
    st = state.loc[dt]
    pos = w.loc[dt]
    pos = pos[pos > 1e-12].sort_values(ascending=False)

    print("=" * 56)
    print(tag if args.breaker else f"{tag}")
    if args.breaker:
        print("规则: A段回撤-8%→银行 | B跑输银行3%/5日→银行 | C单日-3%→仓位50%")
    print(f"信号日: {dt.date()}")
    print(
        f"银行均价={last['bank_avg']:.2f} | 全A均价={last['alla_avg']:.2f} | "
        f"ratio={last['ratio']:.4f}"
    )
    print(f"比价20日: {last['trend']:+.2%} → {direction}")
    print(f"z-score: {last['z']:.2f} | 总仓位建议: {st['exposure']:.0%}")
    print(f"当前腿: {st['leg']}（{'银行等权' if st['leg']=='bank' else '风险动量Top'+str(args.top_n)}）")
    if args.breaker and str(st.get("breaker", "")):
        print(f"熔断标记: {st['breaker']}")
    print("=" * 56)
    print(f"{'代码':<12}{'名称':<10}{'权重':>8}")
    for sym, wt in pos.items():
        print(f"{sym:<12}{NAME_HINT.get(sym, ''):<10}{wt:>7.2%}")
    print("-" * 56)
    if st["leg"] == "bank":
        print("建议: 只持银行腿；不建议购买其他个股。")
        print("懒人替代: 100% 银行ETF（如512800/512000）。")
    else:
        print(f"建议: 等权持有上表 Top{args.top_n}；银行腿仓位=0。")
    print("执行: 信号日收盘后决策，下一交易日调仓（T+1）。")
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    import pandas as pd

    cache = ROOT / "data_cache" / "strategy1"
    close, volume, banks, perf_stats, print_stats = _panels(args.start, cache)

    print("=" * 56)
    print(f"策略{STRATEGY_ID}｜{STRATEGY_NAME}｜回测")
    print(f"回测区间: {args.bt_start} ~ 最新 | top_n={args.top_n}")
    print("=" * 56)

    header = (
        f"{'方案':<16}{'累计收益':>10}{'年化':>10}{'波动':>10}"
        f"{'夏普':>8}{'最大回撤':>10}{'胜率':>8}"
    )
    print(header)
    print("-" * len(header))

    for n in [int(x) for x in args.compare_n.split(",")]:
        cfg = Strategy1Config(top_n=n)
        if args.breaker:
            w, _ = generate_target_weights_breaker(
                close, volume, cfg=cfg, breaker=BreakerConfig(), bank_symbols=banks
            )
            tag = f"{STRATEGY_BREAKER_NAME}_top{n}"
        else:
            w, _ = generate_target_weights(close, volume, cfg=cfg, bank_symbols=banks)
            tag = f"strategy1_top{n}"
        w_bt = w.loc[w.index >= pd.Timestamp(args.bt_start)]
        c_bt = close.loc[close.index >= pd.Timestamp(args.bt_start)]
        w_exec = w_bt.shift(1).fillna(0.0)
        rets = c_bt.pct_change(fill_method=None).fillna(0.0)
        gross = (w_exec * rets).sum(axis=1)
        fee = w_exec.diff().abs().sum(axis=1).fillna(0.0) * (args.fee_bps / 10_000.0)
        net = gross - fee
        print_stats(tag, perf_stats(net))

    return 0


def cmd_compare_breaker(args: argparse.Namespace) -> int:
    """原版 vs 熔断版(A+B+C) 月收益与回撤对比。"""
    import pandas as pd

    cache = ROOT / "data_cache" / "strategy1"
    close, volume, banks, perf_stats, print_stats = _panels(args.start, cache)
    cfg = Strategy1Config(top_n=args.top_n)
    br = BreakerConfig()  # 默认含单日-3%→50%

    w0, _ = generate_target_weights(close, volume, cfg=cfg, bank_symbols=banks)
    w1, st1 = generate_target_weights_breaker(
        close, volume, cfg=cfg, breaker=br, bank_symbols=banks
    )

    def run_net(w):
        rets = close.pct_change(fill_method=None).fillna(0.0)
        we = w.shift(1).fillna(0.0)
        return (we * rets).sum(axis=1) - we.diff().abs().sum(axis=1).fillna(0.0) * (
            args.fee_bps / 10_000.0
        )

    s0 = run_net(w0).loc[args.bt_start : args.bt_end]
    s1 = run_net(w1).loc[args.bt_start : args.bt_end]
    p0, p1 = perf_stats(s0), perf_stats(s1)

    print("=" * 72)
    print(f"策略{STRATEGY_ID}｜{STRATEGY_NAME}  vs  {STRATEGY_BREAKER_NAME}")
    print("熔断规则: A段回撤-8%→银行 | B:5日跑输银行3%→银行 | C:单日-3%→仓位50%")
    print(f"区间: {args.bt_start} ~ {args.bt_end or '最新'} | top_n={args.top_n}")
    print("=" * 72)
    print(f"{'指标':<10}{'策略一':>12}{'策略一熔断版':>14}{'差额':>12}")
    print(
        f"{'累计收益':<10}{p0['total_return']:>+11.2%}{p1['total_return']:>+13.2%}"
        f"{p1['total_return']-p0['total_return']:>+11.2%}"
    )
    print(
        f"{'夏普':<10}{p0['sharpe']:>12.2f}{p1['sharpe']:>14.2f}"
        f"{p1['sharpe']-p0['sharpe']:>+12.2f}"
    )
    print(
        f"{'最大回撤':<10}{p0['max_drawdown']:>+11.2%}{p1['max_drawdown']:>+13.2%}"
        f"{p1['max_drawdown']-p0['max_drawdown']:>+11.2%}"
    )

    print(
        f"\n{'月份':<8}{'策略一':>9}{'熔断版':>9}{'Δ收益':>8}{'策略一DD':>9}{'熔断DD':>9}"
    )
    for m in sorted(set(s0.index.to_period("M")) | set(s1.index.to_period("M"))):
        g0, g1 = s0.loc[str(m)], s1.loc[str(m)]
        if len(g0) == 0 or len(g1) == 0:
            continue
        e0, e1 = (1 + g0).cumprod(), (1 + g1).cumprod()
        print(
            f"{str(m):<8}{e0.iloc[-1]-1:>+8.2%}{e1.iloc[-1]-1:>+8.2%}"
            f"{(e1.iloc[-1]-1)-(e0.iloc[-1]-1):>+7.2%}"
            f"{(e0/e0.cummax()-1).min():>+8.2%}{(e1/e1.cummax()-1).min():>+8.2%}"
        )

    hit = st1.loc[args.bt_start : args.bt_end]
    hit = hit[hit["breaker"].astype(str).str.len() > 0]
    print(
        f"\n熔断触发: {len(hit)}天 | "
        f"A={int(hit['breaker'].str.contains('seg_dd').sum())} | "
        f"B={int(hit['breaker'].str.contains('underperf').sum())} | "
        f"C={int(hit['breaker'].str.contains('day_loss').sum())}"
    )
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """前一天出策略，后一天验证：近 N 个月滚动成功率。"""
    import numpy as np
    import pandas as pd

    cache = ROOT / "data_cache" / "strategy1"
    close, volume, banks, _, _ = _panels(args.start, cache)
    bank_cols = [c for c in banks if c in close.columns]
    exclude = set(bank_cols)

    cfg = Strategy1Config(top_n=args.top_n)
    # 日频决策（验证用）：每天按当日收盘信号，次日验证；选股池每日重算
    cfg_daily = Strategy1Config(
        top_n=args.top_n,
        rebalance="D",  # 每日重选，严格「当天信号」
        z_window=cfg.z_window,
        trend_lookback=cfg.trend_lookback,
    )
    weights, state = generate_target_weights(
        close, volume, cfg=cfg_daily, bank_symbols=banks
    )

    rets = close.pct_change(fill_method=None)
    # 银行腿 / 风险腿 对照收益（风险腿=当日信号选出的动量池；无池时用非银行等权）
    bank_ret = close[bank_cols].pct_change(fill_method=None).mean(axis=1)

    end = close.index.max()
    start = end - pd.DateOffset(months=args.months)
    # 信号日 T 需有 T+1
    signal_days = close.index[(close.index >= start) & (close.index < close.index[-1])]
    # 至少要有 trend
    signal_days = [d for d in signal_days if d in state.index and pd.notna(state.at[d, "trend"])]

    rows = []
    for i, t in enumerate(signal_days):
        # T+1
        loc = close.index.get_loc(t)
        if isinstance(loc, slice) or not isinstance(loc, (int, np.integer)):
            continue
        if loc + 1 >= len(close.index):
            continue
        t1 = close.index[loc + 1]

        leg = state.at[t, "leg"]
        z = float(state.at[t, "z"]) if pd.notna(state.at[t, "z"]) else 0.0
        trend = float(state.at[t, "trend"])
        exposure = float(state.at[t, "exposure"])

        w_t = weights.loc[t]
        # T 日收盘权重 → T+1 日收益
        port_ret = float((w_t * rets.loc[t1]).sum())
        b_ret = float(bank_ret.loc[t1]) if pd.notna(bank_ret.loc[t1]) else 0.0

        # 对照风险腿：用 T 日 risk_names；若银行腿日则仍计算「若选风险」的反事实
        risk_names = [
            s for s in str(state.at[t, "risk_names"]).split(",") if s and s in close.columns
        ]
        if not risk_names:
            # 银行腿日 state 里 risk_names 为空，单独按 T 日重选
            from quant.strategies.dual_anchor import select_risk_names

            risk_names = select_risk_names(
                close, volume, t, top_n=args.top_n, exclude=exclude
            )
        if risk_names:
            r_ret = float(rets.loc[t1, risk_names].mean())
        else:
            non_bank = [c for c in close.columns if c not in exclude]
            r_ret = float(rets.loc[t1, non_bank].mean()) if non_bank else 0.0

        chosen_ret = b_ret if leg == "bank" else r_ret
        other_ret = r_ret if leg == "bank" else b_ret
        # 成功1：选中腿次日收益 ≥ 另一腿（择腿正确）
        leg_win = chosen_ret >= other_ret
        # 成功2：组合次日收益 > 0（绝对赚钱）
        abs_win = port_ret > 0
        # 成功3：组合次日 ≥ 全A等权（相对基准）
        ew_ret = float(rets.loc[t1].mean()) if pd.notna(rets.loc[t1].mean()) else 0.0
        beat_ew = port_ret >= ew_ret

        rows.append(
            {
                "signal_date": t,
                "verify_date": t1,
                "leg": leg,
                "trend": trend,
                "z": z,
                "exposure": exposure,
                "port_ret": port_ret,
                "bank_ret": b_ret,
                "risk_ret": r_ret,
                "ew_ret": ew_ret,
                "leg_win": leg_win,
                "abs_win": abs_win,
                "beat_ew": beat_ew,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        print("无足够样本可验证。")
        return 1

    out = cache / f"validate_{args.months}m_top{args.top_n}.csv"
    cache.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    n = len(df)
    print("=" * 64)
    print(f"策略{STRATEGY_ID}｜{STRATEGY_NAME}｜前一日信号 → 次日验证")
    print(
        f"区间: {df['signal_date'].min().date()} ~ {df['verify_date'].max().date()} "
        f"（近{args.months}个月）| top_n={args.top_n} | 样本={n}对"
    )
    print("规则: T日收盘出腿/持仓，T+1日收益验证（无未来函数）")
    print("=" * 64)

    print("\n【执行成功率】")
    print(f"  择腿成功率（选中腿≥另一腿）: {df['leg_win'].mean():.2%}  ({int(df['leg_win'].sum())}/{n})")
    print(f"  绝对上涨成功率（组合>0）    : {df['abs_win'].mean():.2%}  ({int(df['abs_win'].sum())}/{n})")
    print(f"  相对全A成功率（组合≥等权）  : {df['beat_ew'].mean():.2%}  ({int(df['beat_ew'].sum())}/{n})")

    print("\n【次日收益】")
    print(f"  策略组合 均值/中位: {df['port_ret'].mean():+.2%} / {df['port_ret'].median():+.2%}")
    print(f"  银行腿   均值/中位: {df['bank_ret'].mean():+.2%} / {df['bank_ret'].median():+.2%}")
    print(f"  风险腿   均值/中位: {df['risk_ret'].mean():+.2%} / {df['risk_ret'].median():+.2%}")
    print(f"  全A等权  均值/中位: {df['ew_ret'].mean():+.2%} / {df['ew_ret'].median():+.2%}")
    print(f"  策略累计（简单连乘）: {(1+df['port_ret']).prod()-1:+.2%}")
    print(f"  全A累计（简单连乘）: {(1+df['ew_ret']).prod()-1:+.2%}")

    # 分腿
    print("\n【按信号腿拆分】")
    print(f"{'腿':<8}{'天数':>6}{'择腿成功':>10}{'上涨成功':>10}{'次日均收益':>12}")
    for leg, g in df.groupby("leg"):
        print(
            f"{leg:<8}{len(g):>6}"
            f"{g['leg_win'].mean():>9.2%}"
            f"{g['abs_win'].mean():>9.2%}"
            f"{g['port_ret'].mean():>+11.2%}"
        )

    # 对照：若每天随机猜腿
    rng = np.random.default_rng(42)
    random_leg_win = []
    for _, r in df.iterrows():
        pick_bank = bool(rng.integers(0, 2))
        chosen = r["bank_ret"] if pick_bank else r["risk_ret"]
        other = r["risk_ret"] if pick_bank else r["bank_ret"]
        random_leg_win.append(chosen >= other)
    print(f"\n【对照】随机猜腿成功率: {np.mean(random_leg_win):.2%}（理论约50%）")
    print(f"【对照】银行腿天天持有上涨率: {(df['bank_ret']>0).mean():.2%}")
    print(f"【对照】风险腿天天持有上涨率: {(df['risk_ret']>0).mean():.2%}")

    # 逐日明细（压缩打印）
    print("\n【逐日明细】信号日 → 验证日 | 腿 | 组合T+1 | 择腿 | 上涨")
    print(f"{'信号日':<12}{'验证日':<12}{'腿':<6}{'组合':>8}{'银行':>8}{'风险':>8}{'择腿':>6}{'上涨':>6}")
    for _, r in df.iterrows():
        print(
            f"{r['signal_date'].date()!s:<12}{r['verify_date'].date()!s:<12}{r['leg']:<6}"
            f"{r['port_ret']:>+7.2%}{r['bank_ret']:>+7.2%}{r['risk_ret']:>+7.2%}"
            f"{'Y' if r['leg_win'] else 'N':>6}{'Y' if r['abs_win'] else 'N':>6}"
        )

    print(f"\n明细已保存: {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"策略{STRATEGY_ID}｜{STRATEGY_NAME}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sig = sub.add_parser("signal", help="今日信号与持仓分布")
    sig.add_argument("--top-n", type=int, default=10)
    sig.add_argument("--start", default="2022-01-01")
    sig.add_argument(
        "--breaker",
        action="store_true",
        help="启用熔断 A+B+C（含单日-3%→仓位50%）",
    )
    sig.set_defaults(func=cmd_signal)

    bt = sub.add_parser("backtest", help="近3年回测")
    bt.add_argument("--top-n", type=int, default=10)
    bt.add_argument("--compare-n", default="10,50")
    bt.add_argument("--start", default="2022-01-01")
    bt.add_argument("--bt-start", default="2023-10-30")
    bt.add_argument("--fee-bps", type=float, default=5.0)
    bt.add_argument(
        "--breaker",
        action="store_true",
        help="启用熔断 A+B+C（含单日-3%→仓位50%）",
    )
    bt.set_defaults(func=cmd_backtest)

    val = sub.add_parser("validate", help="近N月：前一日信号→次日验证成功率")
    val.add_argument("--months", type=int, default=2, help="回溯月数")
    val.add_argument("--top-n", type=int, default=10)
    val.add_argument("--start", default="2022-01-01")
    val.set_defaults(func=cmd_validate)

    cmpb = sub.add_parser("compare-breaker", help="原版 vs 熔断版(A+B+C) 对比")
    cmpb.add_argument("--top-n", type=int, default=10)
    cmpb.add_argument("--start", default="2022-01-01")
    cmpb.add_argument("--bt-start", default="2026-01-05")
    cmpb.add_argument("--bt-end", default="2026-10-30")
    cmpb.add_argument("--fee-bps", type=float, default=5.0)
    cmpb.set_defaults(func=cmd_compare_breaker)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
