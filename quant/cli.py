"""命令行入口."""

from __future__ import annotations

import argparse
import sys

from quant.backtest import run_backtest
from quant.data import load_ohlcv
from quant.strategies import SMACrossStrategy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quant", description="量化交易 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    bt = sub.add_parser("backtest", help="运行回测")
    bt.add_argument("--strategy", default="sma", choices=["sma"])
    bt.add_argument("--symbol", default="AAPL")
    bt.add_argument("--start", default="2020-01-01")
    bt.add_argument("--end", default=None)
    bt.add_argument("--fast", type=int, default=10)
    bt.add_argument("--slow", type=int, default=30)
    bt.add_argument("--capital", type=float, default=100_000.0)

    args = parser.parse_args(argv)

    if args.command == "backtest":
        data = load_ohlcv(args.symbol, start=args.start, end=args.end)
        strategy = SMACrossStrategy(fast=args.fast, slow=args.slow)
        result = run_backtest(data, strategy, initial_capital=args.capital)
        summary = result.summary()
        print(f"策略: {strategy.name} | 标的: {args.symbol}")
        print(f"总收益: {summary['total_return']:.2%}")
        print(f"夏普比: {summary['sharpe']:.2f}")
        print(f"最大回撤: {summary['max_drawdown']:.2%}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
