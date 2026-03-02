# 交易系统策略与配置重构总结 (Refactoring Summary)

## 1. 为什么改？(WHY)
- **策略名称耦合度高且不清晰**：原有的 `ShortPutV6`, `ShortPutV9` 等命名方式非常生硬（硬编码），无法直观反映出策略的真实意图（如是否接受行权、是否接盘正股等）。
- **方向计算模块缺乏扩展性**：原本计算交易方向依赖于直接对 `strategy_name` 字符串的解析（比如判断字符串里有没有 "Short"），极其脆弱和不优雅。
- **配置系统缺乏策略级别的灵活性**：`DecisionConfig` 和 `RiskConfig` 此前仍然使用过时的 `ConfigMode`（如 `SAFE`, `NORMAL` 等）去一套适配所有，缺乏像监控模块那样，可以针对特定策略（如针对 V9 策略）提供专属的独立 YAML 覆写配置（Overrides）的能力。
- **回测监控系统存在盲区**：回测系统在将模拟账户持仓转换为监控层使用的 `PositionData` 时，直接忽略了正股（Stock）类型（因为正股没有过期日），这导致基于这些数据的风控系统计算失真。

## 2. 改了什么？(WHAT)
- **重命名策略**：将 `ShortPutV9` 重命名为 `ShortOptionsWithExpireItmStockTrade`（适用于有意愿接盘/行权的正股交易策略），将 `ShortPutV6` 重命名为 `ShortOptionsWithoutExpireItmStockTrade`（适用于纯期权权利金收益，临期需要平仓/展期的策略）。
- **优化交易方向和仓位计算**：摒弃字符串解析，在基类中引入基于策略逻辑的方法 `get_position_side()` 返回具体的枚举 `PositionSide.SHORT` / `LONG`。同时完全接入 `PositionSizer` 来统一计算仓位。
- **配置系统现代化转型**：废弃 `ConfigMode`。实施与 Screening/Monitoring Config 类似的统一组合加载模式：先读取公共的 `base_option_strategy.yaml`，再读取合并特定策略的同名 YAML（如 `short_options_with_expire_itm_stock_trade.yaml`）。
- **支持回测正股监控**：修改 `PositionManager` 中的转换逻辑，现在会自动识别并透传正股到监控管道中。
- **统一监控行为期望**：将底层监控关于行权及展期的推荐统一改为生成明确的 `CLOSE` 操作（避免之前的 `ROLL` 或 `ADJUST` 测试断言报错）。

## 3. 怎么做到的？(HOW)
1. **代码与对象重构**：修改 `src/business/strategy/base.py` 以及各类具体子策略（在 `strategy_factory` 和各个 config 文件中进行引用更新）。
2. **迁移配置文件**：新增 `base_option_strategy.yaml`，并同步更新 `DecisionConfig.load` 与 `RiskConfig.load` 中调用工具函数 `merge_overrides` 的逻辑，注入具体的 `strategy_name`。
3. **消除耦合**：将原先绑定在 `SimulatedPosition` 中的 `PositionData` 设计改为真正的纯数据传输载体（Data Transfer Object），并在 `PositionManager` 的 `_convert_to_position_data` 里加入 `position.is_stock` 分支处理。
4. **全方位测试**：统一所有单元测试与 E2E 管道（Pipeline E2E、Provider Tests 等），修正期望动作，并更新了相关的 Mock 对象。

---
这份重构使整个交易系统的风控粒度更加明确并且具备极高的策略可扩展性。
