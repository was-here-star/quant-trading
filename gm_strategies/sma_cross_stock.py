# coding=utf-8
"""国盛掘金 · 第一个模拟盘策略：A 股日线双均线。

逻辑：
- 标的默认浦发银行 SHSE.600000（可用环境变量覆盖）
- 每个交易日 14:50 计算快/慢均线
- 金叉：目标仓位拉到 GM_TARGET_PERCENT
- 死叉：清空该标的仓位

运行前请确保：
1. 本机已打开「国盛掘金终端」并登录
2. .env 中填写 GM_TOKEN / GM_STRATEGY_ID
3. 仿真模式：在终端「我的策略」中把本策略关联到仿真账户后，
   将 GM_MODE=live 启动
"""

from __future__ import print_function, absolute_import

import os
from pathlib import Path

from dotenv import load_dotenv
from gm.api import (
    ADJUST_PREV,
    MODE_BACKTEST,
    MODE_LIVE,
    OrderType_Limit,
    PositionSide_Long,
    get_position,
    history_n,
    order_target_percent,
    run,
    schedule,
    set_account_id,
)

# 加载仓库根目录 .env（不提交密钥）
_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(_ROOT / ".env")


def init(context):
    context.symbol = os.getenv("GM_SYMBOL", "SHSE.600000")
    context.fast = int(os.getenv("GM_FAST", "5"))
    context.slow = int(os.getenv("GM_SLOW", "20"))
    context.target_percent = float(os.getenv("GM_TARGET_PERCENT", "0.8"))
    context.frequency = "1d"

    if context.fast >= context.slow:
        raise ValueError("GM_FAST 必须小于 GM_SLOW")

    # 尾盘定时决策，兼顾回测与仿真/实盘
    schedule(schedule_func=algo, date_rule="1d", time_rule="14:50:00")
    print(
        "双均线策略已初始化 | symbol={} fast={} slow={} target={:.0%}".format(
            context.symbol, context.fast, context.slow, context.target_percent
        )
    )


def algo(context):
    # 回测/仿真都要显式指定 end_time，否则可能拿到错误窗口数据
    bars = history_n(
        symbol=context.symbol,
        frequency=context.frequency,
        count=context.slow + 2,
        end_time=context.now,
        fields="close,eob",
        fill_missing="Last",
        adjust=ADJUST_PREV,
        adjust_end_time=context.now,
        df=True,
    )
    if bars is None or len(bars) < context.slow + 1:
        print("{} 历史K线不足，跳过".format(context.now))
        return

    closes = bars["close"]
    fast_ma = closes.rolling(context.fast).mean()
    slow_ma = closes.rolling(context.slow).mean()

    # 用前一根已完成的日线判断交叉，避免用到未收盘 bar
    prev_fast, curr_fast = float(fast_ma.iloc[-2]), float(fast_ma.iloc[-1])
    prev_slow, curr_slow = float(slow_ma.iloc[-2]), float(slow_ma.iloc[-1])
    golden = prev_fast <= prev_slow and curr_fast > curr_slow
    death = prev_fast >= prev_slow and curr_fast < curr_slow

    positions = get_position()
    long_pos = [
        p
        for p in positions
        if p["symbol"] == context.symbol and p["side"] == PositionSide_Long
    ]
    has_long = bool(long_pos)
    last_close = float(closes.iloc[-1])

    print(
        "{} close={:.3f} ma{}/{}={:.3f}/{:.3f} pos={}".format(
            context.now,
            last_close,
            context.fast,
            context.slow,
            curr_fast,
            curr_slow,
            long_pos[0]["volume"] if has_long else 0,
        )
    )

    if golden and not has_long:
        print("金叉 -> 买入至目标仓位 {:.0%}".format(context.target_percent))
        order_target_percent(
            symbol=context.symbol,
            percent=context.target_percent,
            order_type=OrderType_Limit,
            position_side=PositionSide_Long,
            price=last_close,
        )
    elif death and has_long:
        print("死叉 -> 清仓")
        order_target_percent(
            symbol=context.symbol,
            percent=0,
            order_type=OrderType_Limit,
            position_side=PositionSide_Long,
            price=last_close,
        )


def on_order_status(context, order):
    if order["status"] == 3:
        print(
            "成交回报 {} {} vol={} price={}".format(
                order["symbol"],
                "买" if order["side"] == 1 else "卖",
                order["volume"],
                order["price"],
            )
        )


def on_backtest_finished(context, indicator):
    print("=" * 48)
    print("回测完成")
    print(indicator)
    print("=" * 48)


def _resolve_mode(mode_name):
    name = (mode_name or "backtest").strip().lower()
    if name in {"live", "sim", "simulation", "paper"}:
        return MODE_LIVE
    return MODE_BACKTEST


if __name__ == "__main__":
    token = os.getenv("GM_TOKEN", "").strip()
    strategy_id = os.getenv("GM_STRATEGY_ID", "").strip()
    if not token:
        raise SystemExit("请在 .env 中设置 GM_TOKEN（国盛掘金终端 -> 系统设置 -> 密钥管理）")
    if not strategy_id:
        raise SystemExit(
            "请在 .env 中设置 GM_STRATEGY_ID（终端新建策略后，在策略编辑页右下角查看）"
        )

    account_id = os.getenv("GM_ACCOUNT_ID", "").strip()
    if account_id:
        set_account_id(account_id)

    mode = _resolve_mode(os.getenv("GM_MODE", "backtest"))
    mode_label = "仿真/实时(MODE_LIVE)" if mode == MODE_LIVE else "回测(MODE_BACKTEST)"
    print("启动模式: {}".format(mode_label))

    run(
        strategy_id=strategy_id,
        filename=os.path.basename(__file__),
        mode=mode,
        token=token,
        backtest_start_time=os.getenv("GM_BT_START", "2024-01-01 09:00:00"),
        backtest_end_time=os.getenv("GM_BT_END", "2024-06-30 15:00:00"),
        backtest_adjust=ADJUST_PREV,
        backtest_initial_cash=float(os.getenv("GM_BT_CASH", "1000000")),
        backtest_commission_ratio=float(os.getenv("GM_BT_COMMISSION", "0.0003")),
        backtest_slippage_ratio=float(os.getenv("GM_BT_SLIPPAGE", "0.0001")),
    )
