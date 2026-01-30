# 经济日历迁移计划: Finnhub → FMP

## 背景

Finnhub Economic Calendar API 需要付费订阅 ($50/month)，改用免费的 FMP (Financial Modeling Prep) API。

**FMP 优势**:
- 免费 tier: 250 calls/day（足够每天查询一次）
- 覆盖完整: FOMC, CPI, NFP, GDP, PCE 等
- API 简洁: `/stable/economic-calendar?from=YYYY-MM-DD&to=YYYY-MM-DD`
- 每 15 分钟更新

---

## 代码变更计划

### Phase 1: 创建 FmpCalendarProvider

**新建文件**: `src/data/providers/fmp_calendar_provider.py`

```python
class FmpCalendarProvider:
    """FMP Economic Calendar API provider."""

    BASE_URL = "https://financialmodelingprep.com/stable"

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("FMP_API_KEY")

    @property
    def is_available(self) -> bool

    def get_economic_calendar(
        self, start_date: date, end_date: date, country: str | None = None
    ) -> EventCalendar | None

    def get_market_moving_events(
        self, start_date: date, end_date: date
    ) -> list[EconomicEvent]

    def check_blackout_period(
        self, target_date: date, blackout_days: int = 3, ...
    ) -> tuple[bool, list[EconomicEvent]]
```

**API 端点**:
```
GET /stable/economic-calendar?from=2025-01-01&to=2025-01-31&apikey=XXX
```

**响应格式** (预期):
```json
[
  {
    "date": "2025-01-29",
    "country": "US",
    "event": "Fed Interest Rate Decision",
    "actual": null,
    "previous": "4.5%",
    "estimate": "4.5%",
    "impact": "High"
  }
]
```

### Phase 2: 更新 UnifiedDataProvider

**修改文件**: `src/data/providers/unified_provider.py`

变更:
1. 导入 `FmpCalendarProvider` 替换 `FinnhubProvider`
2. 初始化时创建 `FmpCalendarProvider` 实例
3. 更新 `get_economic_calendar()` 方法调用
4. 更新 `check_macro_blackout()` 方法调用

```python
# Before
from src.data.providers.finnhub_provider import FinnhubProvider
self._finnhub_provider = FinnhubProvider()

# After
from src.data.providers.fmp_calendar_provider import FmpCalendarProvider
self._fmp_calendar_provider = FmpCalendarProvider()
```

### Phase 3: 更新 providers/__init__.py

**修改文件**: `src/data/providers/__init__.py`

变更:
1. 移除 `FinnhubProvider` 导出
2. 移除 `LocalCalendarProvider` 导出
3. 添加 `FmpCalendarProvider` 导出

### Phase 4: 更新 MarketFilter

**修改文件**: `src/business/screening/filters/market_filter.py`

检查 `_check_macro_events()` 是否需要更新:
- 如果使用 `UnifiedDataProvider.check_macro_blackout()` → 无需修改
- 如果直接使用 provider → 更新为 FMP

### Phase 5: 更新验证脚本

**修改文件**:
- `tests/business/screening/validate_macro_events.py`
- `tests/business/screening/test_macro_events_validation.py`

变更:
1. 将 Finnhub 相关测试改为 FMP
2. 更新 API key 环境变量名: `FINNHUB_API_KEY` → `FMP_API_KEY`
3. 更新 mock 数据格式

### Phase 6: 删除废弃文件

**删除文件**:
- `src/data/providers/finnhub_provider.py`
- `src/data/providers/local_calendar_provider.py`
- `config/screening/economic_calendar.yaml` (静态日历配置)

### Phase 7: 更新配置

**修改文件**: `.env.example` (如有)

变更:
```bash
# Before
FINNHUB_API_KEY=your_finnhub_api_key

# After
FMP_API_KEY=your_fmp_api_key
```

---

## 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 新建 | `src/data/providers/fmp_calendar_provider.py` | FMP API 客户端 |
| 修改 | `src/data/providers/unified_provider.py` | 使用 FMP provider |
| 修改 | `src/data/providers/__init__.py` | 更新导出 |
| 修改 | `tests/business/screening/validate_macro_events.py` | FMP 验证 |
| 修改 | `tests/business/screening/test_macro_events_validation.py` | FMP 测试 |
| 删除 | `src/data/providers/finnhub_provider.py` | 废弃 |
| 删除 | `src/data/providers/local_calendar_provider.py` | 废弃 |
| 删除 | `config/screening/economic_calendar.yaml` | 废弃 |

---

## 事件类型映射

FMP 事件名称 → 系统 `EconomicEventType`:

| FMP Event | EconomicEventType |
|-----------|-------------------|
| Fed Interest Rate Decision | FOMC |
| FOMC Meeting | FOMC |
| CPI / Consumer Price Index | CPI |
| Inflation Rate | CPI |
| Nonfarm Payrolls | NFP |
| NFP / Employment | NFP |
| GDP / Gross Domestic Product | GDP |
| PCE / Personal Consumption | PCE |
| PPI / Producer Price Index | PPI |
| Retail Sales | RETAIL_SALES |
| Unemployment Rate | UNEMPLOYMENT |
| 其他 | OTHER |

---

## 验收标准

1. ✅ `FmpCalendarProvider` 能获取未来 30 天事件
2. ✅ 事件类型正确映射到 `EconomicEventType`
3. ✅ `MarketFilter._check_macro_events()` 正常工作
4. ✅ Blackout 检查在 FOMC/CPI/NFP 前 3 天触发
5. ✅ API key 未配置时优雅降级（返回空列表）
6. ✅ 验证脚本 `validate_macro_events.py` 通过
7. ✅ 所有单元测试通过

---

## 执行顺序

1. 创建 `FmpCalendarProvider` 并编写单元测试
2. 验证 FMP API 响应格式（需要真实 API key）
3. 更新 `UnifiedDataProvider`
4. 更新测试脚本
5. 运行集成测试
6. 删除废弃文件
7. 提交代码
