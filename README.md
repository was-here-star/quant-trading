# Quant

量化交易研究与回测框架；支持本地「国盛掘金终端」仿真交易。

## 功能

- 行情数据获取与缓存
- 策略开发（信号 / 仓位）
- 历史回测与绩效分析
- 国盛掘金（掘金 3）本地终端仿真 / 回测

## 快速开始（研究框架）

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

运行示例回测：

```bash
python -m quant.cli backtest --strategy sma --symbol AAPL
```

## 国盛掘金 · 第一个模拟盘策略

策略文件：`gm_strategies/sma_cross_stock.py`（A 股日线双均线，默认 `SHSE.600000`）。

### 1. 准备本地终端

1. 打开并登录 **国盛掘金终端**（本机服务需在线）
2. **账户管理** → 新建 **仿真账户**（设置名称与期初资金）
3. **量化研究** → **新建策略**（可先建空策略）
4. 打开策略编辑页，右下角复制 **strategy_id**
5. **系统设置 → 密钥管理** 复制 **token**
6. 在「我的策略」对该策略点 **交易**，关联刚建的仿真账户

### 2. 安装掘金 SDK（建议独立虚拟环境）

```bash
python -m venv .venv-gm
.venv-gm\Scripts\activate
pip install -r requirements-gm.txt -i https://mirrors.aliyun.com/pypi/simple/
```

### 3. 配置环境变量

```bash
copy .env.example .env
```

填写 `GM_TOKEN`、`GM_STRATEGY_ID`。仿真运行前将 `GM_MODE=live`。

### 4. 运行

先回测验证连通性：

```bash
.venv-gm\Scripts\python.exe gm_strategies\sma_cross_stock.py
```

再切仿真（终端已关联仿真账户，且 `GM_MODE=live`）：

```bash
.venv-gm\Scripts\python.exe gm_strategies\sma_cross_stock.py
```

也可把 `gm_strategies/sma_cross_stock.py` 内容拷入终端策略编辑器，在终端内直接启动仿真。

## 项目结构

```
quant/
  data/          # 数据加载与缓存
  strategies/    # 研究侧交易策略
  backtest/      # 回测引擎
  execution/     # 实盘 / 模拟执行（预留）
  utils/         # 工具函数
gm_strategies/   # 国盛掘金终端策略（gm SDK）
tests/
```

## 配置

复制环境变量模板并按需填写：

```bash
copy .env.example .env
```

## 许可证

MIT
