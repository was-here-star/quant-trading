"""策略1 应用入口：今日信号 / 持仓分布 / 回测 / 熔断对比 / 看板。

用法:
  python scripts/strategy1.py signal
  python scripts/strategy1.py signal --breaker          # 启用 A+B+C 熔断
  python scripts/strategy1.py backtest --breaker
  python scripts/strategy1.py compare-breaker           # 2026至今 原版 vs 熔断
  python scripts/strategy1.py dashboard                 # 刷行情并重写看板 HTML
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from volume_surge_prob import A_SHARE_UNIVERSE, _normalize_ohlcv, download_panel

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
from quant.strategies.zenmeshu import (
    DEFAULT_BANK_ETF,
    DEFAULT_RISK_ETFS,
    ZenmeshuConfig,
    generate_target_weights_zenmeshu,
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

# 策略样本池中文名（看板/信号展示用）
NAME_HINT = {
    **BANK_NAMES,
    "600009.SS": "上海机场",
    "600019.SS": "宝钢股份",
    "600028.SS": "中国石化",
    "600030.SS": "中信证券",
    "600031.SS": "三一重工",
    "600048.SS": "保利发展",
    "600050.SS": "中国联通",
    "600104.SS": "上汽集团",
    "600111.SS": "北方稀土",
    "600150.SS": "中国船舶",
    "600196.SS": "复星医药",
    "600276.SS": "恒瑞医药",
    "600309.SS": "万华化学",
    "600346.SS": "恒力石化",
    "600406.SS": "国电南瑞",
    "600436.SS": "片仔癀",
    "600438.SS": "通威股份",
    "600519.SS": "贵州茅台",
    "600547.SS": "山东黄金",
    "600570.SS": "恒生电子",
    "600585.SS": "海螺水泥",
    "600588.SS": "用友网络",
    "600690.SS": "海尔智家",
    "600703.SS": "三安光电",
    "600745.SS": "闻泰科技",
    "600809.SS": "山西汾酒",
    "600887.SS": "伊利股份",
    "600893.SS": "航发动力",
    "600900.SS": "长江电力",
    "600938.SS": "中国海油",
    "600941.SS": "中国移动",
    "601012.SS": "隆基绿能",
    "601066.SS": "中信建投",
    "601088.SS": "中国神华",
    "601211.SS": "国泰君安",
    "601225.SS": "陕西煤业",
    "601318.SS": "中国平安",
    "601336.SS": "新华保险",
    "601601.SS": "中国太保",
    "601628.SS": "中国人寿",
    "601633.SS": "长城汽车",
    "601668.SS": "中国建筑",
    "601688.SS": "华泰证券",
    "601728.SS": "中国电信",
    "601766.SS": "中国中车",
    "601800.SS": "中国交建",
    "601816.SS": "京沪高铁",
    "601857.SS": "中国石油",
    "601888.SS": "中国中免",
    "601899.SS": "紫金矿业",
    "601919.SS": "中远海控",
    "601985.SS": "中国核电",
    "601995.SS": "中金公司",
    "603259.SS": "药明康德",
    "603288.SS": "海天味业",
    "603501.SS": "韦尔股份",
    "603799.SS": "华友钴业",
    "603986.SS": "兆易创新",
    "000002.SZ": "万科A",
    "000063.SZ": "中兴通讯",
    "000100.SZ": "TCL科技",
    "000157.SZ": "中联重科",
    "000166.SZ": "申万宏源",
    "000301.SZ": "东方盛虹",
    "000333.SZ": "美的集团",
    "000338.SZ": "潍柴动力",
    "000425.SZ": "徐工机械",
    "000538.SZ": "云南白药",
    "000568.SZ": "泸州老窖",
    "000596.SZ": "古井贡酒",
    "000625.SZ": "长安汽车",
    "000651.SZ": "格力电器",
    "000661.SZ": "长春高新",
    "000725.SZ": "京东方A",
    "000768.SZ": "中航西飞",
    "000776.SZ": "广发证券",
    "000786.SZ": "北新建材",
    "000858.SZ": "五粮液",
    "000876.SZ": "新希望",
    "000895.SZ": "双汇发展",
    "000938.SZ": "紫光股份",
    "000977.SZ": "浪潮信息",
    "001979.SZ": "招商蛇口",
    "002001.SZ": "新和成",
    "002027.SZ": "分众传媒",
    "002049.SZ": "紫光国微",
    "002050.SZ": "三花智控",
    "002179.SZ": "中航光电",
    "002230.SZ": "科大讯飞",
    "002236.SZ": "大华股份",
    "002241.SZ": "歌尔股份",
    "002271.SZ": "东方雨虹",
    "002304.SZ": "洋河股份",
    "002352.SZ": "顺丰控股",
    "002371.SZ": "北方华创",
    "002415.SZ": "海康威视",
    "002460.SZ": "赣锋锂业",
    "002466.SZ": "天齐锂业",
    "002475.SZ": "立讯精密",
    "002594.SZ": "比亚迪",
    "002714.SZ": "牧原股份",
    "002812.SZ": "恩捷股份",
    "002821.SZ": "凯莱英",
    "002920.SZ": "德赛西威",
    "003816.SZ": "中国广核",
    "300015.SZ": "爱尔眼科",
    "300059.SZ": "东方财富",
    "300122.SZ": "智飞生物",
    "300124.SZ": "汇川技术",
    "300142.SZ": "沃森生物",
    "300274.SZ": "阳光电源",
    "300308.SZ": "中际旭创",
    "300347.SZ": "泰格医药",
    "300408.SZ": "三环集团",
    "300413.SZ": "芒果超媒",
    "300433.SZ": "蓝思科技",
    "300450.SZ": "先导智能",
    "300498.SZ": "温氏股份",
    "300750.SZ": "宁德时代",
    "300759.SZ": "康龙化成",
    "300760.SZ": "迈瑞医疗",
    "300782.SZ": "卓胜微",
    "300896.SZ": "爱美客",
    "300999.SZ": "金龙鱼",
    # ETF
    **DEFAULT_RISK_ETFS,
    DEFAULT_BANK_ETF: "银行ETF",
    "512800.SS": "银行ETF",
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

    cfg = Strategy1Config(top_n=args.top_n, rebalance=args.rebalance)
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

    # 最近/下一调仓日
    rebal_mask = state["rebalance"] if "rebalance" in state.columns else None
    last_rebal = (
        state.index[rebal_mask][-1].date()
        if rebal_mask is not None and rebal_mask.any()
        else None
    )
    is_rebal_today = bool(st.get("rebalance", False))

    print("=" * 56)
    print(tag if args.breaker else f"{tag}")
    print(f"调仓频率: {args.rebalance}（默认月末，月内持仓不动）")
    if args.breaker:
        print("规则: A段回撤-8%→银行 | B跑输银行3%/5日→银行 | C单日-3%→仓位50%")
    print(f"信号日: {dt.date()} | 今日是否调仓日: {'是' if is_rebal_today else '否'}")
    if last_rebal:
        print(f"最近调仓日: {last_rebal}")
    print(
        f"银行均价={last['bank_avg']:.2f} | 全A均价={last['alla_avg']:.2f} | "
        f"ratio={last['ratio']:.4f}"
    )
    print(f"比价20日: {last['trend']:+.2%} → {direction}")
    print(f"z-score: {last['z']:.2f} | 总仓位建议: {st['exposure']:.0%}")
    print(f"当前持仓腿: {st['leg']}（{'银行等权' if st['leg']=='bank' else '风险动量Top'+str(args.top_n)}）")
    if "signal_leg" in st.index:
        print(f"当日即时信号腿: {st['signal_leg']}（仅供参考；月频以持仓腿为准）")
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
    if is_rebal_today:
        print("执行: 本日为月末调仓日，收盘决策 → 下一交易日换仓（T+1）。")
    else:
        print("执行: 非调仓日，维持现有持仓，无需操作；等到月末再决策。")
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


def _refresh_cache(cache_dir: Path, start: str, lookback_days: int = 40) -> int:
    """强制增量刷新 yfinance 日线，合并进本地 pkl（有缓存也会更新）。"""
    import pandas as pd
    import yfinance as yf

    cache_dir.mkdir(parents=True, exist_ok=True)
    refresh_start = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    updated = 0
    batch = 25
    for i in range(0, len(A_SHARE_UNIVERSE), batch):
        chunk = A_SHARE_UNIVERSE[i : i + batch]
        try:
            raw = yf.download(
                chunk,
                start=refresh_start,
                end=None,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
        except Exception:
            continue
        for sym in chunk:
            path = cache_dir / f"{sym}_{start}_na.pkl"
            try:
                fresh = _normalize_ohlcv((raw if len(chunk) == 1 else raw[sym]).copy())
            except Exception:
                continue
            if fresh.empty:
                continue
            if path.exists():
                old = pd.read_pickle(path)
                combined = pd.concat([old, fresh])
                combined = combined[~combined.index.duplicated(keep="last")].sort_index()
            else:
                combined = fresh
            combined.to_pickle(path)
            updated += 1
    return updated


def _z_history_series(
    close_long,
    banks,
    cfg: Strategy1Config,
    years: int = 10,
) -> list[dict]:
    """近 N 年双锚 z 水位（周频抽样，供看板时序图）。"""
    import pandas as pd

    anchors = build_anchors(
        close_long,
        banks,
        z_window=cfg.z_window,
        trend_lookback=cfg.trend_lookback,
    )
    z = anchors["z"].dropna()
    if z.empty:
        return []
    end = z.index.max()
    start = end - pd.DateOffset(years=years)
    z = z.loc[z.index >= start]
    # 周频末值，控制 HTML 体积
    try:
        z_w = z.resample("W-FRI").last().dropna()
    except ValueError:
        z_w = z.resample("W").last().dropna()
    return [
        {"d": str(i.date()), "z": round(float(v), 3)}
        for i, v in z_w.items()
        if pd.notna(v)
    ]


def _flatten_ohlcv_columns(df: "pd.DataFrame") -> "pd.DataFrame":
    """兼容 yfinance MultiIndex 列名 → open/high/low/close/volume。"""
    import pandas as pd

    if not isinstance(df.columns, pd.MultiIndex):
        # 可能已是 ('close', 'code') 被读成 tuple 单层
        if len(df.columns) and isinstance(df.columns[0], tuple):
            df = df.copy()
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df
    # MultiIndex: level0=field, level1=ticker 或相反
    lvl0 = [str(x).lower() for x in df.columns.get_level_values(0)]
    if any(x in ("close", "open", "adj close") for x in lvl0):
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns.get_level_values(0)]
    else:
        df = df.copy()
        df.columns = [str(c).lower() for c in df.columns.get_level_values(1)]
    return df


def _price_panel_for_weights(
    w: "pd.DataFrame",
    stock_close: "pd.DataFrame",
    etf_close: "pd.DataFrame | None" = None,
) -> "pd.DataFrame":
    """把权重列对应的价格拼成宽表（股票+ETF）。"""
    import pandas as pd

    parts = [stock_close]
    if etf_close is not None and not etf_close.empty:
        parts.append(etf_close.reindex(stock_close.index).ffill())
    wide = pd.concat(parts, axis=1)
    wide = wide.loc[:, ~wide.columns.duplicated()]
    cols = [c for c in w.columns if c in wide.columns]
    return wide[cols]


def _build_dashboard_payload(
    close,
    volume,
    banks,
    cfg: Strategy1Config,
    fee_bps: float = 5.0,
    close_long=None,
    z_years: int = 3,
    *,
    use_breaker: bool = False,
    use_zenmeshu: bool = False,
    etf_close=None,
    display_name: str | None = None,
    horizon_years: int | None = None,
) -> dict:
    import numpy as np
    import pandas as pd

    etf_close = etf_close if etf_close is not None else pd.DataFrame()

    if use_zenmeshu:
        zcfg = ZenmeshuConfig(
            z_window=cfg.z_window,
            trend_lookback=cfg.trend_lookback,
            rebalance=cfg.rebalance,
        )
        w, state = generate_target_weights_zenmeshu(close, etf_close, cfg=zcfg)
        name = display_name or STRATEGY_BREAKER_NAME
        px_panel = _price_panel_for_weights(w, close, etf_close)
    else:
        base_w, base_st = generate_target_weights(
            close, volume, cfg=cfg, bank_symbols=banks
        )
        if use_breaker:
            w, state = generate_target_weights_breaker(
                close, volume, cfg=cfg, breaker=BreakerConfig(), bank_symbols=banks
            )
            if "rebalance" not in state.columns:
                state = state.copy()
                state["rebalance"] = base_st["rebalance"].reindex(state.index).fillna(False)
            if "signal_leg" not in state.columns:
                state = state.copy()
                state["signal_leg"] = (
                    base_st["signal_leg"].reindex(state.index)
                    if "signal_leg" in base_st.columns
                    else state["leg"]
                )
            name = display_name or "熔断版"
        else:
            w, state = base_w, base_st
            name = display_name or STRATEGY_NAME
        px_panel = close.reindex(columns=w.columns)

    anchors = build_anchors(
        close, banks, z_window=cfg.z_window, trend_lookback=cfg.trend_lookback
    )
    last = state.index[-1]
    st = state.loc[last]
    an = anchors.loc[last]

    hold = w.loc[last]
    hold = hold[hold > 1e-6].sort_values(ascending=False)
    rows = []
    for sym, wt in hold.items():
        if sym not in px_panel.columns:
            continue
        px = float(px_panel[sym].loc[last]) if pd.notna(px_panel[sym].loc[last]) else float("nan")
        prev = px_panel[sym].shift(1).loc[last]
        chg = float(px / prev - 1) if pd.notna(prev) and prev and pd.notna(px) else None
        code = str(sym).replace(".SS", "").replace(".SZ", "")
        rows.append(
            {
                "code": code,
                "name": NAME_HINT.get(sym, DEFAULT_RISK_ETFS.get(sym, sym)),
                "weight": round(float(wt), 4),
                "price": None if px != px else round(px, 2),
                "chg": None if chg is None else round(chg, 4),
            }
        )

    rets = px_panel.pct_change(fill_method=None).fillna(0.0)
    we = w.reindex(columns=px_panel.columns).fillna(0.0).shift(1).fillna(0.0)
    net = (we * rets).sum(axis=1) - we.diff().abs().sum(axis=1).fillna(0.0) * (
        fee_bps / 10_000.0
    )
    ytd_start = f"{last.year}-01-01"
    net_ytd = net.loc[ytd_start:]
    eq = (1 + net_ytd).cumprod()
    ytd = float(eq.iloc[-1] - 1) if len(eq) else None
    # 今日实时：当前持仓按最新日收益加权（日线源；盘中为源站最新价相对昨收）
    today_ret = float(net.loc[last]) if last in net.index and pd.notna(net.loc[last]) else None
    # 本月累计（自然月 MTD）
    mtd_start = pd.Timestamp(last.year, last.month, 1)
    net_mtd = net.loc[mtd_start:last]
    mtd = float((1 + net_mtd).prod() - 1) if len(net_mtd) else None
    # 年化：当年至今按交易日折年；另给近1年（样本够时）
    def _ann(s: pd.Series) -> float | None:
        s = s.dropna()
        if len(s) < 5:
            return None
        e = float((1 + s).prod())
        return float(e ** (252 / len(s)) - 1)

    ann_ytd = _ann(net_ytd)
    net_1y = net.loc[last - pd.DateOffset(years=1) :]
    ann_1y = _ann(net_1y)
    ret_1y = float((1 + net_1y).prod() - 1) if len(net_1y) else None

    z_v = float(an["z"]) if pd.notna(an["z"]) else 0.0
    trend_v = float(an["trend"]) if pd.notna(an["trend"]) else 0.0
    temp = float(np.clip((z_v + 3) / 6 * 100, 0, 100))
    rebal_dates = state.index[state["rebalance"]]
    last_rebal = rebal_dates[-1] if len(rebal_dates) else last

    hist_close = close_long if close_long is not None else close
    z_hist = _z_history_series(hist_close, banks, cfg, years=z_years)
    # 用短样本最新日补齐末点，避免长缓存滞后
    asof = str(last.date())
    if z_hist and z_hist[-1]["d"] < asof:
        z_hist.append({"d": asof, "z": round(z_v, 3)})
    elif not z_hist:
        z_hist = [{"d": asof, "z": round(z_v, 3)}]

    # 长周期（如 10 年）累计 / 年化 / 最大回撤
    horizon_start = None
    ret_horizon = None
    ann_horizon = None
    mdd_horizon = None
    yearly_review: list[dict] = []
    if horizon_years and horizon_years > 0:
        horizon_start = last - pd.DateOffset(years=int(horizon_years))
        net_h = net.loc[net.index >= horizon_start]
        if len(net_h):
            ret_horizon = float((1 + net_h).prod() - 1)
            ann_horizon = _ann(net_h)
            eq_h = (1 + net_h).cumprod()
            mdd_horizon = float((eq_h / eq_h.cummax() - 1.0).min())
        years = pd.period_range(
            horizon_start.to_period("Y"), last.to_period("Y"), freq="Y"
        )
        for per in years:
            y_start = per.to_timestamp()
            y_end = (per + 1).to_timestamp() - pd.Timedelta(days=1)
            seg = net.loc[(net.index >= max(y_start, horizon_start)) & (net.index <= min(y_end, last))]
            if len(seg) == 0:
                continue
            y_ret = float((1 + seg).prod() - 1)
            snap_dt = seg.index[0]
            snap_w = we.loc[snap_dt]
            snap_w = snap_w[snap_w > 1e-6].sort_values(ascending=False)
            hold_rows = []
            for sym, wt in snap_w.head(12).items():
                code = str(sym).replace(".SS", "").replace(".SZ", "")
                hold_rows.append(
                    {
                        "code": code,
                        "name": NAME_HINT.get(
                            sym, DEFAULT_RISK_ETFS.get(sym, code)
                        ),
                        "weight": round(float(wt), 4),
                    }
                )
            st_y = state.loc[snap_dt] if snap_dt in state.index else None
            yearly_review.append(
                {
                    "year": str(per.year),
                    "return": round(y_ret, 4),
                    "leg": str(st_y["leg"]) if st_y is not None else "",
                    "exposure": round(float(st_y["exposure"]), 4)
                    if st_y is not None
                    else round(float(snap_w.sum()), 4),
                    "holdings": hold_rows,
                }
            )

    # 近12个自然月：当月收益 + 月初实际持仓（T+1 执行后的权重）
    monthly_review: list[dict] = []
    start_1y = (last - pd.DateOffset(years=1)).replace(day=1)
    months = pd.period_range(start_1y.to_period("M"), last.to_period("M"), freq="M")
    for per in months:
        m_start = per.to_timestamp()
        m_end = (per + 1).to_timestamp() - pd.Timedelta(days=1)
        seg = net.loc[(net.index >= m_start) & (net.index <= min(m_end, last))]
        if len(seg) == 0:
            continue
        m_ret = float((1 + seg).prod() - 1)
        # 持仓快照：该月第一个交易日的执行权重
        snap_dt = seg.index[0]
        snap_w = we.loc[snap_dt]
        snap_w = snap_w[snap_w > 1e-6].sort_values(ascending=False)
        hold_rows = []
        for sym, wt in snap_w.items():
            code = str(sym).replace(".SS", "").replace(".SZ", "")
            hold_rows.append(
                {
                    "code": code,
                    "name": NAME_HINT.get(
                        sym, DEFAULT_RISK_ETFS.get(sym, code)
                    ),
                    "weight": round(float(wt), 4),
                }
            )
        st_m = state.loc[snap_dt] if snap_dt in state.index else None
        m_risk = (
            round(float(st_m["risk_weight"]), 4)
            if st_m is not None and "risk_weight" in state.columns
            else None
        )
        m_bank = (
            round(float(st_m["bank_weight"]), 4)
            if st_m is not None and "bank_weight" in state.columns
            else None
        )
        monthly_review.append(
            {
                "month": str(per),
                "return": round(m_ret, 4),
                "leg": str(st_m["leg"]) if st_m is not None else "",
                "exposure": round(float(st_m["exposure"]), 4)
                if st_m is not None
                else round(float(snap_w.sum()), 4),
                "risk_weight": m_risk,
                "bank_weight": m_bank,
                "holdings": hold_rows,
            }
        )

    alert = str(st["alert"]) if "alert" in state.columns and pd.notna(st.get("alert")) else ""
    picks = str(st["risk_etf_picks"]) if "risk_etf_picks" in state.columns else ""
    risk_w = (
        round(float(st["risk_weight"]), 4)
        if "risk_weight" in state.columns
        else (0.0 if str(st["leg"]) == "bank" else round(float(st["exposure"]), 4))
    )
    bank_w = (
        round(float(st["bank_weight"]), 4)
        if "bank_weight" in state.columns
        else (round(float(st["exposure"]), 4) if str(st["leg"]) == "bank" else 0.0)
    )

    return {
        "asof": str(last.date()),
        "strategy": name,
        "variant": "zenmeshu" if use_zenmeshu else ("breaker" if use_breaker else "zhidhong"),
        "rebalance": cfg.rebalance,
        "is_rebal": bool(st["rebalance"]),
        "last_rebal": str(last_rebal.date()),
        "next_hint": "约本月最后一个交易日",
        "leg": str(st["leg"]),
        "signal_leg": str(st.get("signal_leg", st["leg"])),
        "alert": alert,
        "risk_etf_picks": picks,
        "z": round(z_v, 2),
        "trend": round(trend_v, 4),
        "exposure": round(float(st["exposure"]), 4),
        "risk_weight": risk_w,
        "bank_weight": bank_w,
        "risk_share": round(float(st["risk_share"]), 4)
        if "risk_share" in state.columns
        else risk_w,
        "bank_avg": round(float(an["bank_avg"]), 2),
        "alla_avg": round(float(an["alla_avg"]), 2),
        "ratio": round(float(an["ratio"]), 4),
        "temp": round(temp, 1),
        "ytd_return": None if ytd is None else round(ytd, 4),
        "today_return": None if today_ret is None else round(today_ret, 4),
        "mtd_return": None if mtd is None else round(mtd, 4),
        "ann_return": None if ann_ytd is None else round(ann_ytd, 4),
        "ann_return_1y": None if ann_1y is None else round(ann_1y, 4),
        "return_1y": None if ret_1y is None else round(ret_1y, 4),
        "horizon_years": int(horizon_years) if horizon_years else None,
        "horizon_start": str(horizon_start.date()) if horizon_start is not None else None,
        "return_horizon": None if ret_horizon is None else round(ret_horizon, 4),
        "ann_return_horizon": None if ann_horizon is None else round(ann_horizon, 4),
        "max_drawdown_horizon": None if mdd_horizon is None else round(mdd_horizon, 4),
        "holdings": rows,
        "cash": round(max(0.0, 1.0 - float(st["exposure"])), 4),
        "z_years": z_years,
        "z_hist": z_hist,
        "monthly_review": monthly_review,
        "yearly_review": yearly_review,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def cmd_dashboard(args: argparse.Namespace) -> int:
    """刷行情并重写策略一看板 HTML（默认强制拉到 yfinance 最新交易日）。"""
    import pandas as pd

    cache = ROOT / "data_cache" / "strategy1"
    long_cache = ROOT / "data_cache" / "strategy1_long"
    horizon_years = getattr(args, "horizon_years", None)
    # 长周期看板用长样本缓存（2006 起），保证 10 年权重/收益可算
    use_long_panel = bool(horizon_years and horizon_years >= 5)
    panel_start = "2006-01-01" if use_long_panel else args.start
    panel_cache = long_cache if use_long_panel else cache

    if not args.no_refresh:
        print(f"正在刷新到最新日线…（本地日 {datetime.now().strftime('%Y-%m-%d %H:%M')}）")
        n = _refresh_cache(cache, start=args.start, lookback_days=args.lookback_days)
        print(f"短样本缓存：更新 {n} 只")
        # 长样本也增量刷新，保证水位图末日与信号一致
        if long_cache.exists() or args.refresh_long or use_long_panel:
            long_cache.mkdir(parents=True, exist_ok=True)
            n2 = _refresh_cache(
                long_cache, start="2006-01-01", lookback_days=args.lookback_days
            )
            print(f"长样本缓存：更新 {n2} 只")
    else:
        print("跳过联网刷新（--no-refresh），使用本地缓存")

    if use_long_panel and not panel_cache.exists():
        raise SystemExit("长样本缓存不存在，请先去掉 --no-refresh 或加 --refresh-long")

    close, volume, banks, _, _ = _panels(panel_start, panel_cache)
    # 短样本补齐末日（长缓存偶发滞后）
    if use_long_panel and cache.exists():
        try:
            close_s, volume_s, _, _, _ = _panels(args.start, cache)
            common = close.columns.intersection(close_s.columns)
            if len(common):
                close = (
                    pd.concat([close[common], close_s[common]], axis=0)
                    .sort_index()
                )
                close = close[~close.index.duplicated(keep="last")]
                volume = (
                    pd.concat(
                        [volume.reindex(columns=common), volume_s.reindex(columns=common)],
                        axis=0,
                    )
                    .sort_index()
                )
                volume = volume[~volume.index.duplicated(keep="last")].reindex(close.index).fillna(0.0)
        except Exception as e:
            print(f"短样本补齐跳过: {e}")
    # 长周期看板：默认日频（与历史约+450%报告口径）；--horizon-monthly 出月末独立文档
    horizon_monthly = bool(getattr(args, "horizon_monthly", False))
    if use_long_panel and getattr(args, "variant", "zhidhong") != "zenmeshu":
        rebal = "BME" if horizon_monthly else "D"
        print(
            f"长周期回测调仓: {rebal}"
            + ("（月频独立文档）" if horizon_monthly else "（日频/历史长报告口径）")
        )
    else:
        rebal = args.rebalance
    cfg = Strategy1Config(top_n=args.top_n, rebalance=rebal)

    # 水位图优先长样本；并用短样本最新日补齐末段
    close_long = None
    if long_cache.exists():
        try:
            from deviation_cta_backtest import build_close_panel

            long_panel = download_panel(
                A_SHARE_UNIVERSE, start="2006-01-01", end=None, cache_dir=long_cache
            )
            close_long = build_close_panel(long_panel)
            # 短样本可能更新更快：按列对齐后拼接，keep='last'
            common = close_long.columns.intersection(close.columns)
            if len(common):
                merged = pd.concat([close_long[common], close[common]], axis=0)
                merged = merged[~merged.index.duplicated(keep="last")].sort_index()
                # 保留长样本独有列
                extra = close_long.columns.difference(common)
                if len(extra):
                    close_long = merged.join(close_long[extra], how="left")
                else:
                    close_long = merged
            print(
                f"长样本水位: {close_long.index.min().date()} → {close_long.index.max().date()}"
            )
        except Exception as e:
            print(f"长样本加载失败，改用短样本画水位图: {e}")

    use_zenmeshu = getattr(args, "variant", "zhidhong") == "zenmeshu"
    use_breaker = (not use_zenmeshu) and getattr(args, "breaker", False)
    display_name = (
        STRATEGY_BREAKER_NAME
        if use_zenmeshu
        else (STRATEGY_NAME if not use_breaker else "熔断版")
    )
    is_daily_rebal = str(getattr(args, "rebalance", "BME")).upper() in (
        "D",
        "DAY",
        "DAILY",
    )
    # --near-1y：近一年专版；--rebalance D 也走近一年布局
    near_1y = bool(getattr(args, "near_1y", False) or is_daily_rebal) and not bool(
        horizon_years
    )
    if horizon_years and not use_zenmeshu:
        freq_tag = "月频" if horizon_monthly else "日频"
        display_name = f"{display_name} · {int(horizon_years)}年期 · {freq_tag}"
    elif near_1y and not use_zenmeshu and not use_breaker:
        display_name = (
            f"{display_name} · 近一年日频"
            if is_daily_rebal
            else f"{display_name} · 近一年月频"
        )
    z_years = int(horizon_years) if horizon_years else args.z_years

    # 怎么输策略：额外下载风险 ETF + 银行 ETF
    etf_close = pd.DataFrame()
    if use_zenmeshu:
        from deviation_cta_backtest import build_close_panel

        etf_syms = list(DEFAULT_RISK_ETFS.keys()) + [DEFAULT_BANK_ETF]
        etf_cache = ROOT / "data_cache" / "strategy1_etf"
        etf_cache.mkdir(parents=True, exist_ok=True)
        import yfinance as yf

        if not args.no_refresh:
            refresh_start = (
                datetime.now() - timedelta(days=max(args.lookback_days, 200))
            ).strftime("%Y-%m-%d")
            raw = yf.download(
                etf_syms,
                start=refresh_start,
                end=None,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                progress=False,
            )
            updated = 0
            for sym in etf_syms:
                path = etf_cache / f"{sym}_{args.start}_na.pkl"
                try:
                    fresh = _flatten_ohlcv_columns(
                        _normalize_ohlcv(
                            (raw if len(etf_syms) == 1 else raw[sym]).copy()
                        )
                    )
                except Exception:
                    continue
                if fresh.empty:
                    continue
                if path.exists():
                    old = _flatten_ohlcv_columns(pd.read_pickle(path))
                    combined = pd.concat([old, fresh])
                    combined = combined[
                        ~combined.index.duplicated(keep="last")
                    ].sort_index()
                else:
                    long_raw = yf.download(
                        sym,
                        start=args.start,
                        end=None,
                        auto_adjust=True,
                        progress=False,
                        threads=False,
                    )
                    combined = _flatten_ohlcv_columns(
                        _normalize_ohlcv(long_raw.copy())
                    )
                    if combined.empty:
                        combined = fresh
                combined.to_pickle(path)
                updated += 1
            print(f"ETF 缓存：更新 {updated} 只")
        else:
            for sym in etf_syms:
                path = etf_cache / f"{sym}_{args.start}_na.pkl"
                if path.exists():
                    # 修复历史 MultiIndex 缓存
                    old = _flatten_ohlcv_columns(pd.read_pickle(path))
                    old.to_pickle(path)
                    continue
                long_raw = yf.download(
                    sym,
                    start=args.start,
                    end=None,
                    auto_adjust=True,
                    progress=False,
                    threads=False,
                )
                combined = _flatten_ohlcv_columns(_normalize_ohlcv(long_raw.copy()))
                if not combined.empty:
                    combined.to_pickle(path)
        # 直接从扁平缓存拼 close，避免 MultiIndex 坑
        closes = {}
        for sym in etf_syms:
            path = etf_cache / f"{sym}_{args.start}_na.pkl"
            if not path.exists():
                continue
            df = _flatten_ohlcv_columns(pd.read_pickle(path))
            if "close" not in df.columns or df.empty:
                continue
            s = df["close"].astype(float).copy()
            s.index = pd.to_datetime(s.index).tz_localize(None)
            closes[sym] = s
        etf_close = pd.DataFrame(closes).sort_index()
        print(
            f"ETF 行情: {etf_close.index.min().date() if len(etf_close) else '-'} → "
            f"{etf_close.index.max().date() if len(etf_close) else '-'} | n={etf_close.shape}"
        )

    payload = _build_dashboard_payload(
        close,
        volume,
        banks,
        cfg,
        fee_bps=args.fee_bps,
        close_long=close_long if close_long is not None else (close if use_long_panel else None),
        z_years=z_years,
        use_breaker=use_breaker,
        use_zenmeshu=use_zenmeshu,
        etf_close=etf_close,
        display_name=display_name,
        horizon_years=int(horizon_years) if horizon_years else None,
    )
    # 近一年专版 / 长周期：禁止被实时服务跳转覆盖
    if payload.get("horizon_years") or near_1y or is_daily_rebal:
        payload["live_redirect"] = False
    # 近一年看板：水位区额外展示一张近1年图
    if near_1y and not use_zenmeshu:
        payload["z_panel_1y"] = True

    today = datetime.now().strftime("%Y-%m-%d")
    if payload["asof"] < today:
        print(
            f"注意：信号日={payload['asof']}，今天={today}。"
            f"若今日为交易日且尚未收盘/源未入库，属正常延迟；收盘后再刷一次即可对齐。"
        )
    else:
        print(f"已对齐最新交易日：{payload['asof']}")

    template_path = (
        Path(args.template)
        if args.template
        else Path(__file__).resolve().parent / "templates" / "strategy1_dashboard.html"
    )
    template = template_path.read_text(encoding="utf-8")
    if "__DASHBOARD_DATA__" not in template:
        raise SystemExit(f"模板缺少占位符 __DASHBOARD_DATA__: {template_path}")

    data_js = json.dumps(payload, ensure_ascii=False, indent=2)
    html = template.replace("__DASHBOARD_DATA__", data_js)

    outs: list[Path] = []
    if args.out:
        outs = [Path(p) for p in args.out]
    elif use_zenmeshu:
        outs = [
            ROOT / "data_cache" / "strategy1" / "zenmeshu_dashboard.html",
            Path.home() / "Desktop" / "怎么输看板.html",
        ]
    elif horizon_years:
        tag = f"{int(horizon_years)}y"
        if horizon_monthly:
            outs = [
                ROOT
                / "data_cache"
                / "strategy1"
                / f"zhidhong_dashboard_{tag}_monthly.html",
                Path.home() / "Desktop" / f"指定红看板-{int(horizon_years)}年-月频.html",
            ]
        else:
            outs = [
                ROOT / "data_cache" / "strategy1" / f"zhidhong_dashboard_{tag}.html",
                Path.home() / "Desktop" / f"指定红看板-{int(horizon_years)}年.html",
            ]
    elif near_1y and is_daily_rebal:
        outs = [
            ROOT / "data_cache" / "strategy1" / "zhidhong_dashboard_1y_daily.html",
            Path.home() / "Desktop" / "指定红看板-近一年.html",
        ]
    elif near_1y:
        # 月末 BME 近一年专版，独立文件，不被实时服务覆盖
        outs = [
            ROOT / "data_cache" / "strategy1" / "zhidhong_dashboard_1y_monthly.html",
            Path.home() / "Desktop" / "指定红看板-近一年-月频.html",
        ]
    else:
        outs = [
            ROOT / "data_cache" / "strategy1" / "strategy1_dashboard.html",
            Path.home() / "Desktop" / "指定红看板.html",
            Path.home() / "Downloads" / "stock_dashboard.html",
        ]

    for path in outs:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(html, encoding="utf-8")
            print(f"已写入: {path}")
        except OSError as e:
            print(f"写入失败（跳过）: {path} ({e})")

    if use_zenmeshu:
        json_name = "zenmeshu_dashboard_data.json"
    elif horizon_years:
        json_name = (
            f"zhidhong_dashboard_{int(horizon_years)}y_monthly_data.json"
            if horizon_monthly
            else f"zhidhong_dashboard_{int(horizon_years)}y_data.json"
        )
    elif near_1y and is_daily_rebal:
        json_name = "zhidhong_dashboard_1y_daily_data.json"
    elif near_1y:
        json_name = "zhidhong_dashboard_1y_monthly_data.json"
    else:
        json_name = "dashboard_data.json"
    json_path = ROOT / "data_cache" / "strategy1" / json_name
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"数据快照: {json_path}")
    print(
        f"策略={payload['strategy']} | 信号日={payload['asof']} | 腿={payload['leg']} | "
        f"z={payload['z']} | 仓位={payload['exposure']:.0%} | "
        f"调仓日={'是' if payload['is_rebal'] else '否'}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=f"策略{STRATEGY_ID}｜{STRATEGY_NAME}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sig = sub.add_parser("signal", help="今日信号与持仓分布")
    sig.add_argument("--top-n", type=int, default=10)
    sig.add_argument("--start", default="2022-01-01")
    sig.add_argument(
        "--rebalance",
        default="BME",
        help="调仓频率，默认 BME=月末；周频可用 W-FRI",
    )
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

    dash = sub.add_parser("dashboard", help="刷行情并重写策略一看板 HTML")
    dash.add_argument("--top-n", type=int, default=10)
    dash.add_argument("--start", default="2022-01-01")
    dash.add_argument("--rebalance", default="BME")
    dash.add_argument("--fee-bps", type=float, default=5.0)
    dash.add_argument(
        "--variant",
        choices=["zhidhong", "zenmeshu"],
        default="zhidhong",
        help="zhidhong=指定红策略；zenmeshu=怎么输策略(ETF分仓优化版)",
    )
    dash.add_argument(
        "--breaker",
        action="store_true",
        help="旧熔断版看板（一般用 --variant zenmeshu）",
    )
    dash.add_argument(
        "--z-years",
        type=int,
        default=3,
        help="偏离度水位图回溯年数（默认近3年）",
    )
    dash.add_argument(
        "--horizon-years",
        type=int,
        default=None,
        help="长周期看板年数（如 10=指定红10年期，默认日频；加 --horizon-monthly 为月频独立文档）",
    )
    dash.add_argument(
        "--horizon-monthly",
        action="store_true",
        help="长周期看板用月末BME，输出独立文档（如 指定红看板-10年-月频.html）",
    )
    dash.add_argument(
        "--near-1y",
        action="store_true",
        help="近一年专版看板（默认月末BME→指定红看板-近一年-月频；配合 --rebalance D 为日频）",
    )
    dash.add_argument(
        "--lookback-days",
        type=int,
        default=40,
        help="增量刷新回溯天数",
    )
    dash.add_argument(
        "--no-refresh",
        action="store_true",
        help="不拉网，仅用本地缓存重写 HTML",
    )
    dash.add_argument(
        "--refresh-long",
        action="store_true",
        help="即使长样本目录不存在也创建并刷新（默认有目录才刷）",
    )
    dash.add_argument(
        "--out",
        action="append",
        help="输出 HTML 路径，可多次指定；默认写项目缓存 + Downloads",
    )
    dash.add_argument(
        "--template",
        default="",
        help="看板模板路径（需含 __DASHBOARD_DATA__）",
    )
    dash.set_defaults(func=cmd_dashboard)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
