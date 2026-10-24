# Quant

量化交易研究与回测框架。

## 功能

- 行情数据获取与缓存
- 策略开发（信号 / 仓位）
- 历史回测与绩效分析
- 可扩展的券商 / 执行接口预留

## 快速开始

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

运行示例回测：

```bash
python -m quant.cli backtest --strategy sma --symbol AAPL
```

## 项目结构

```
quant/
  data/          # 数据加载与缓存
  strategies/    # 交易策略
  backtest/      # 回测引擎
  execution/     # 实盘 / 模拟执行（预留）
  utils/         # 工具函数
tests/
```

## 配置

复制环境变量模板并按需填写：

```bash
cp .env.example .env
```

## 许可证

MIT
