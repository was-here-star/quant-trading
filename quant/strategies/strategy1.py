"""策略1：双锚偏离度截取（类 CTA）。

来源文案要点
------------
市场规律不在故事，在价格偏离度；截取偏离度数值 = 截取流动性溢价。
两个核心价格指数：
  - 银行算术平均股价 = 分配权
  - 全A平均股价     = 定价权
两者偏离度 → 过热/过冷 → 情绪与流动性 → 牛熊。
A股难做空：用「风险腿 ↔ 银行腿」切换，向上向下都能参与。
底层类 CTA；样本缩到 Top10/Top50 增强收益。

规则（周频调仓，T+1 生效）
--------------------------
1. ratio = 全A均价 / 银行均价
2. z = zscore(log(ratio), 60)
3. 比价20日 > 0 → 100% 风险腿（流动性前2N → 动量前N）
4. 比价20日 ≤ 0 → 100% 银行腿（银行等权）
5. |z| > 2 → 总仓位 × 0.5
"""

from __future__ import annotations

from quant.strategies.dual_anchor import (
    DEFAULT_BANKS,
    DualAnchorConfig,
    build_anchors,
    generate_target_weights,
    select_risk_names,
)

STRATEGY_ID = 1
STRATEGY_NAME = "双锚偏离度截取"
STRATEGY_CODE = "strategy1"

# 策略1默认参数
Strategy1Config = DualAnchorConfig

__all__ = [
    "STRATEGY_ID",
    "STRATEGY_NAME",
    "STRATEGY_CODE",
    "Strategy1Config",
    "DEFAULT_BANKS",
    "DualAnchorConfig",
    "build_anchors",
    "generate_target_weights",
    "select_risk_names",
]
