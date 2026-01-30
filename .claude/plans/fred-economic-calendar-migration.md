# FRED + Static FOMC 经济日历迁移计划

## 背景

FMP (Financial Modeling Prep) Economic Calendar API 需要付费订阅 (Starter 起步 $15.96/月)。
经研究，采用 **FRED API + 静态 FOMC 日历** 混合方案作为免费替代。

## 数据源方案

| 数据类型 | 数据源 | API/配置 | 免费额度 |
|----------|--------|----------|----------|
| CPI | FRED API | release_id=10 | 120次/分钟 |
| NFP | FRED API | release_id=50 | 120次/分钟 |
| GDP | FRED API | release_id=53 | 120次/分钟 |
| PPI | FRED API | release_id=46 | 120次/分钟 |
| FOMC | 静态 YAML | fomc_calendar.yaml | 无限制 |

## 实现阶段

### Phase 1: 创建 FRED Calendar Provider

**新建文件**: `src/data/providers/fred_calendar_provider.py`

```python
class FredCalendarProvider:
    """FRED API provider for economic release dates."""

    BASE_URL = "https://api.stlouisfed.org/fred"

    # Release IDs
    RELEASE_CPI = 10
    RELEASE_NFP = 50  # Employment Situation
    RELEASE_GDP = 53
    RELEASE_PPI = 46

    def __init__(self, api_key: str | None = None):
        self._api_key = api_key or os.environ.get("FRED_API_KEY")

    def get_release_dates(
        self,
        release_id: int,
        start_date: date,
        end_date: date,
    ) -> list[EconomicEvent]:
        """获取指定发布类型的未来发布日期."""
        params = {
            "release_id": release_id,
            "realtime_start": start_date.isoformat(),
            "realtime_end": end_date.isoformat(),
            "include_release_dates_with_no_data": "true",
            "file_type": "json",
            "api_key": self._api_key,
        }
        # ... API 调用逻辑
```

### Phase 2: 创建静态 FOMC 日历

**新建文件**: `config/screening/fomc_calendar.yaml`

```yaml
# FOMC 会议日期
# 数据来源: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
# 更新频率: 每年初更新

fomc_meetings:
  2025:
    - 2025-01-29  # Jan 28-29
    - 2025-03-19  # Mar 18-19* (SEP)
    - 2025-05-07  # May 6-7
    - 2025-06-18  # Jun 17-18* (SEP)
    - 2025-07-30  # Jul 29-30
    - 2025-09-17  # Sep 16-17* (SEP)
    - 2025-10-29  # Oct 28-29
    - 2025-12-10  # Dec 9-10* (SEP)

  2026:
    - 2026-01-28  # Jan 27-28
    - 2026-03-18  # Mar 17-18* (SEP)
    - 2026-04-29  # Apr 28-29
    - 2026-06-17  # Jun 16-17* (SEP)
    - 2026-07-29  # Jul 28-29
    - 2026-09-16  # Sep 15-16* (SEP)
    - 2026-10-28  # Oct 27-28
    - 2026-12-09  # Dec 8-9* (SEP)

# * 标记表示包含 Summary of Economic Projections
```

### Phase 3: 创建整合 Provider

**新建文件**: `src/data/providers/economic_calendar_provider.py`

```python
class EconomicCalendarProvider:
    """整合 FRED API + 静态 FOMC 的经济日历提供者."""

    def __init__(self, fred_api_key: str | None = None):
        self._fred = FredCalendarProvider(api_key=fred_api_key)
        self._fomc_dates = self._load_fomc_calendar()

    def get_economic_calendar(
        self,
        start_date: date,
        end_date: date,
        event_types: list[str] | None = None,
    ) -> EventCalendar:
        """获取完整经济日历 (FRED + FOMC)."""
        events = []

        # 从 FRED 获取 CPI/NFP/GDP/PPI
        if event_types is None or "CPI" in event_types:
            events.extend(self._fred.get_release_dates(
                FredCalendarProvider.RELEASE_CPI, start_date, end_date))
        if event_types is None or "NFP" in event_types:
            events.extend(self._fred.get_release_dates(
                FredCalendarProvider.RELEASE_NFP, start_date, end_date))
        # ...

        # 从静态配置获取 FOMC
        if event_types is None or "FOMC" in event_types:
            events.extend(self._get_fomc_events(start_date, end_date))

        return EventCalendar(
            start_date=start_date,
            end_date=end_date,
            events=sorted(events, key=lambda e: e.event_date),
            source="fred+static",
        )

    def check_blackout_period(
        self,
        target_date: date,
        blackout_days: int = 3,
        blackout_events: list[str] | None = None,
    ) -> tuple[bool, list[EconomicEvent]]:
        """检查是否处于 blackout 期间."""
        # ... 实现逻辑
```

### Phase 4: 更新 UnifiedDataProvider

**修改文件**: `src/data/providers/unified_provider.py`

```python
# 删除
from src.data.providers.fmp_calendar_provider import FmpCalendarProvider
self._fmp_calendar = fmp_calendar_provider

# 添加
from src.data.providers.economic_calendar_provider import EconomicCalendarProvider
self._economic_calendar = economic_calendar_provider

# 更新方法
def get_economic_calendar(self, start: date, end: date) -> EventCalendar | None:
    return self._economic_calendar.get_economic_calendar(start, end)

def check_macro_blackout(self, target_date: date, ...) -> tuple[bool, list[EconomicEvent]]:
    return self._economic_calendar.check_blackout_period(target_date, ...)
```

### Phase 5: 更新 providers/__init__.py

**修改文件**: `src/data/providers/__init__.py`

```python
# 删除
from src.data.providers.fmp_calendar_provider import FmpCalendarProvider

# 添加
from src.data.providers.fred_calendar_provider import FredCalendarProvider
from src.data.providers.economic_calendar_provider import EconomicCalendarProvider

__all__ = [
    # ...
    "FredCalendarProvider",
    "EconomicCalendarProvider",
]
```

### Phase 6: 更新验证脚本

**修改文件**:
- `tests/business/screening/validate_macro_events.py`
- `tests/business/screening/test_macro_events_validation.py`

将所有 FMP 相关引用改为 FRED + EconomicCalendarProvider。

### Phase 7: 删除废弃文件

**删除文件**: `src/data/providers/fmp_calendar_provider.py`

---

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/data/providers/fred_calendar_provider.py` | 新建 | FRED API 客户端 |
| `config/screening/fomc_calendar.yaml` | 新建 | 静态 FOMC 日历 |
| `src/data/providers/economic_calendar_provider.py` | 新建 | 整合提供者 |
| `src/data/providers/unified_provider.py` | 修改 | 使用新提供者 |
| `src/data/providers/__init__.py` | 修改 | 更新导出 |
| `tests/business/screening/validate_macro_events.py` | 修改 | 使用新提供者 |
| `tests/business/screening/test_macro_events_validation.py` | 修改 | 使用新提供者 |
| `src/data/providers/fmp_calendar_provider.py` | 删除 | 废弃 |

---

## 验收标准

1. [ ] `FredCalendarProvider` 能正确获取 CPI/NFP/GDP/PPI 发布日期
2. [ ] 静态 FOMC 日历包含 2025-2026 年所有会议日期
3. [ ] `EconomicCalendarProvider.get_economic_calendar()` 返回合并后的事件列表
4. [ ] `check_blackout_period()` 正确判断 FOMC/CPI/NFP 前的 blackout 期
5. [ ] 所有验证测试通过
6. [ ] `fmp_calendar_provider.py` 已删除

---

## 环境变量配置

```bash
# FRED API Key (免费注册获取)
# https://fred.stlouisfed.org/docs/api/api_key.html
export FRED_API_KEY=your_api_key
```

---

## 执行顺序

1. 创建 `fred_calendar_provider.py`
2. 创建 `fomc_calendar.yaml`
3. 创建 `economic_calendar_provider.py`
4. 更新 `unified_provider.py`
5. 更新 `providers/__init__.py`
6. 更新验证脚本
7. 运行测试验证
8. 删除 `fmp_calendar_provider.py`
