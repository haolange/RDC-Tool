"""rdx-tools 的 performance counter 采样 service。

将 RenderDoc 的 GPU performance counter APIs（枚举、描述、抓取、分析）
封装为适用于 CLI/runtime handlers 的 async 接口。

``renderdoc`` module 采用延迟导入，使其余包可在无该 module 时加载与测试。

关键能力：
    * 枚举可用的 GPU performance counters 及其元数据。
    * 在指定 event 范围内采样 counters，生成 per-event samples、
      per-counter summaries 以及统计异常。
    * 基于 GPU duration 检测性能热点 event。
"""

from __future__ import annotations

import asyncio
import functools
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

from rdx.models import PerfResult, CounterSample, CounterSummary

logger = logging.getLogger("rdx.core.perf_service")


async def measure_frame_gpu(controller: Any, rd: Any, *, samples: int, warmup: int) -> Dict[str, Any]:
    """Read the native whole-replay counter; never aggregate event durations."""
    if not 1 <= samples <= 16 or not 0 <= warmup <= 4:
        raise ValueError("Frame measurement requires 1..16 samples and 0..4 warmup runs")
    counter = getattr(rd.GPUCounter, "FrameGPUDuration", None)
    if counter is None:
        raise RuntimeError("Native runtime lacks the whole-replay GPU counter; update the matching runtime")
    available = await asyncio.to_thread(controller.EnumerateCounters)
    if counter not in available:
        raise RuntimeError("Whole-replay GPU timestamps unavailable for this backend or queue configuration")
    desc = await asyncio.to_thread(controller.DescribeCounter, counter)
    if int(desc.unit) != _COUNTER_UNIT_SECONDS or int(desc.resultType) != _COMP_TYPE_FLOAT or int(desc.resultByteWidth) != 8:
        raise ValueError("Whole-replay counter has an invalid unit or result format")
    pending = list(await asyncio.to_thread(controller.GetRootActions))
    events = []
    while pending:
        action = pending.pop()
        events.append(int(action.eventId))
        pending.extend(action.children)
    if not events:
        raise ValueError("Capture has no replay event range")
    values = []
    for index in range(samples + warmup):
        rows = list(await asyncio.to_thread(controller.FetchCounters, [counter]))
        if len(rows) != 1 or rows[0].counter != counter or int(rows[0].eventId) != 0:
            raise RuntimeError("Whole-replay GPU timestamp query failed or returned an incomplete sample")
        value = _extract_counter_value(rows[0], desc)
        if value <= 0:
            raise ValueError("Whole-replay GPU duration must be positive")
        if index >= warmup:
            values.append(value)
    return {"method": "gpu_timestamp_full_replay", "unit": "seconds", "valid": True,
            "scope": "single_queue_complete_replay", "range": {"first_event_id": 1, "last_event_id": max(events)},
            "samples": values, "sampling": {"samples": samples, "warmup": warmup},
            "includes_replay_scheduling_gaps": True, "includes_initial_contents": False,
            "original_application_frame_time": False, "counter_id": int(counter)}

# ---------------------------------------------------------------------------
# Lazy renderdoc import（延迟导入）
# ---------------------------------------------------------------------------

_rd_module: Any = None
_rd_import_attempted: bool = False


def _lazy_import_renderdoc() -> Any:
    """首次使用时导入 ``renderdoc``。

    成功返回 module 对象，失败返回 ``None``。
    """
    global _rd_module, _rd_import_attempted

    if _rd_import_attempted:
        return _rd_module

    _rd_import_attempted = True
    try:
        import renderdoc as rd  # type: ignore[import-not-found]
        _rd_module = rd
        logger.debug("renderdoc module loaded successfully")
    except ImportError:
        logger.warning(
            "renderdoc Python module not found. Performance counter "
            "sampling 将不可用。请确保 module 在 sys.path 中或设置 "
            "RDX_RENDERDOC_PATH。"
        )
        _rd_module = None

    return _rd_module


# ---------------------------------------------------------------------------
# Helpers（辅助）
# ---------------------------------------------------------------------------

# RenderDoc's public enum values. The Python binding stringifies these enums as
# their numeric value on current builds, so result decoding must use ``int``
# rather than matching display names.
_COMP_TYPE_FLOAT = 1
_COMP_TYPE_UINT = 4
_COUNTER_UNIT_SECONDS = 1

# 常见 GPU-duration counter 名称（按优先级检查）。
_GPU_DURATION_NAMES: Tuple[str, ...] = (
    "EventGPUDuration",
    "GPUDuration",
    "GPU Duration",
)

# 标准异常 z-score 阈值（mean + N * std）。
_ANOMALY_Z_THRESHOLD: float = 3.0


def _extract_counter_value(result: Any, desc: Any) -> float:
    """从 ``CounterValue`` union 中提取标量数值。

    Parameters
    ----------
    result:
        ``CounterResult`` 实例，其 ``.value`` 属性为 ``CounterValue`` union。
    desc:
        该 counter 的 ``CounterDescription``，用于通过 ``resultType``
        确定读取哪个 union 成员。

    Returns
    -------
    float
        提取并转换为 Python float 的数值。
    """
    value_obj = result.value
    try:
        result_type = int(desc.resultType)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported GPU counter result type: {desc.resultType!r}") from exc
    byte_width = int(getattr(desc, "resultByteWidth", 0) or 0)
    if result_type == _COMP_TYPE_FLOAT and byte_width in {4, 8}:
        accessor = "f" if byte_width == 4 else "d"
    elif result_type == _COMP_TYPE_UINT and byte_width in {4, 8}:
        accessor = "u32" if byte_width == 4 else "u64"
    else:
        raise ValueError(
            f"Unsupported GPU counter result type/width: {result_type}/{byte_width}"
        )
    if hasattr(value_obj, accessor):
        value = float(getattr(value_obj, accessor))
        if not math.isfinite(value):
            raise ValueError("GPU counter returned a non-finite value")
        return value
    raise ValueError(f"GPU counter value is missing the {accessor} union member")


def _duration_to_microseconds(value: float, desc: Any) -> float:
    """Convert a RenderDoc duration counter value to microseconds."""
    try:
        unit = int(desc.unit)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Unsupported GPU duration counter unit: {desc.unit!r}") from exc
    if unit != _COUNTER_UNIT_SECONDS:
        raise ValueError(f"Unsupported GPU duration counter unit: {unit}")
    duration_us = value * 1_000_000.0
    if not math.isfinite(duration_us):
        raise ValueError("GPU duration conversion produced a non-finite value")
    return duration_us


def _compute_p95(values: List[float]) -> float:
    """在不使用 NumPy 的情况下计算 *values* 的 95 分位数。

    使用与 ``numpy.percentile(values, 95, interpolation='linear')`` 一致的
    线性插值方法。

    空列表返回 ``0.0``。
    """
    if not values:
        return 0.0

    n = len(values)
    if n == 1:
        return values[0]

    sorted_vals = sorted(values)

    # 使用 C = 1 约定计算 95 分位的秩。
    rank = 0.95 * (n - 1)
    lo_idx = int(math.floor(rank))
    hi_idx = min(lo_idx + 1, n - 1)
    frac = rank - lo_idx

    return sorted_vals[lo_idx] + frac * (sorted_vals[hi_idx] - sorted_vals[lo_idx])


def _compute_std(values: List[float], mean: float) -> float:
    """计算总体标准差。"""
    if len(values) < 2:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


# ---------------------------------------------------------------------------
# PerfService
# ---------------------------------------------------------------------------


class PerfService:
    """GPU performance counter 操作的高层 async service。

    所有公开方法都接收松耦合的 service 引用（session_manager），
    以保持无状态并便于使用 fakes/mocks 测试。
    """

    # ------------------------------------------------------------------
    # Executor helper（执行器辅助）
    # ------------------------------------------------------------------

    @staticmethod
    async def _offload(fn: Any, *args: Any, **kwargs: Any) -> Any:
        """在默认 thread-pool executor 中运行同步 callable。"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, functools.partial(fn, *args, **kwargs),
        )

    # ------------------------------------------------------------------
    # enumerate_counters
    # ------------------------------------------------------------------

    async def enumerate_counters(
        self,
        session_id: str,
        session_manager: Any,
    ) -> List[Dict[str, Any]]:
        """返回可用 GPU performance counters 及其描述。

        Each entry in the returned list is a dict with keys:

        * ``counter_id`` (``int``)  -- numeric value of the ``GPUCounter`` enum.
        * ``name`` (``str``)        -- human-readable counter name.
        * ``description`` (``str``) -- longer description from the driver.
        * ``unit`` (``str``)        -- measurement unit (e.g. ``"seconds"``,
          ``"percentage"``).
        * ``result_type`` (``str``) -- value type (``Float``, ``UInt32``,
          ``UInt64``, ``Double``).

        Parameters
        ----------
        session_id:
            活跃 session identifier。
        session_manager:
            提供 ``get_controller(session_id)`` 以获取 replay controller。

        Returns
        -------
        list[dict]
            Counter descriptions. Runtime and driver read failures raise errors.
        """
        rd = _lazy_import_renderdoc()
        if rd is None:
            logger.warning("renderdoc unavailable; returning empty counter list")
            raise RuntimeError("GPU counter query unavailable")

        try:
            controller = session_manager.get_controller(session_id)
        except Exception as exc:
            logger.warning(
                "Failed to get controller for session %s: %s",
                session_id, exc,
            )
            raise RuntimeError("GPU counter read failed") from exc

        try:
            counter_enums = await self._offload(controller.EnumerateCounters)
        except Exception as exc:
            logger.error("EnumerateCounters failed: %s", exc)
            raise RuntimeError("GPU counter read failed") from exc

        results: List[Dict[str, Any]] = []
        for counter in counter_enums:
            try:
                desc = await self._offload(
                    controller.DescribeCounter, counter,
                )
                results.append({
                    "counter_id": int(counter),
                    "name": str(getattr(desc, "name", "")),
                    "description": str(getattr(desc, "description", "")),
                    "unit": str(getattr(desc, "unit", "")),
                    "result_type": str(getattr(desc, "resultType", "")),
                })
            except Exception as exc:
                logger.warning(
                    "DescribeCounter failed for counter %s: %s",
                    counter, exc,
                )
                raise RuntimeError("GPU counter read failed") from exc

        logger.debug(
            "Enumerated %d counters for session %s",
            len(results), session_id,
        )
        return results

    # ------------------------------------------------------------------
    # sample_counters
    # ------------------------------------------------------------------

    async def sample_counters(
        self,
        session_id: str,
        event_range: Tuple[int, int],
        counter_ids: List[int],
        session_manager: Any,
    ) -> PerfResult:
        """抓取并分析指定 event 范围内的 performance counters。

        Parameters
        ----------
        session_id:
            活跃 session identifier。
        event_range:
            ``(lo, hi)`` 闭区间 event-ID 边界。仅包含 ``eventId`` 位于该范围的结果。
        counter_ids:
            要采样的 ``GPUCounter`` 整数值列表。可使用 :meth:`enumerate_counters`
            返回的 ``counter_id``。
        session_manager:
            提供 replay controller。

        Returns
        -------
        PerfResult
            包含 ``samples``（per-event、per-counter 值）、
            ``summaries``（per-counter 统计：min、max、mean、p95、hotspot event），
            以及 ``anomaly_events``（任一 counter 超过 mean + 3*std 的 event IDs）。
        """
        rd = _lazy_import_renderdoc()
        if rd is None:
            logger.warning("renderdoc unavailable; returning empty PerfResult")
            raise RuntimeError("GPU counter sampling unavailable")

        try:
            controller = session_manager.get_controller(session_id)
        except Exception as exc:
            logger.warning(
                "Failed to get controller for session %s: %s",
                session_id, exc,
            )
            raise RuntimeError("GPU counter read failed") from exc

        lo, hi = event_range
        if lo < 0 or hi < lo:
            raise ValueError("Invalid counter event range")

        # -- 从整数 ID 解析 GPUCounter enums ------------------------------
        counter_list: List[Any] = []
        try:
            all_counters = await self._offload(controller.EnumerateCounters)
            available_map: Dict[int, Any] = {
                int(c): c for c in all_counters
            }
        except Exception as exc:
            logger.error("EnumerateCounters failed: %s", exc)
            raise RuntimeError("GPU counter read failed") from exc

        for cid in counter_ids:
            if cid in available_map:
                counter_list.append(available_map[cid])
            else:
                raise ValueError(f"Requested counter_id {cid} is unavailable on this GPU")

        if not counter_list:
            logger.warning("No valid counters to sample")
            raise RuntimeError("GPU counter sampling unavailable")

        # -- 构建 counter description 查找表 ------------------------------
        desc_map: Dict[int, Any] = {}
        name_map: Dict[int, str] = {}
        for counter in counter_list:
            try:
                desc = await self._offload(
                    controller.DescribeCounter, counter,
                )
                desc_map[int(counter)] = desc
                name_map[int(counter)] = str(getattr(desc, "name", ""))
            except Exception as exc:
                logger.warning(
                    "DescribeCounter failed for %s: %s", counter, exc,
                )

        # -- 抓取 counters ------------------------------------------------
        try:
            raw_results = await self._offload(
                controller.FetchCounters, counter_list,
            )
        except Exception as exc:
            logger.error("FetchCounters failed: %s", exc)
            raise RuntimeError("GPU counter read failed") from exc

        # -- 过滤到 event 范围并构建 samples -------------------------------
        samples: List[CounterSample] = []
        # 累加器：counter_id -> (event_id, value) 列表。
        per_counter: Dict[int, List[Tuple[int, float]]] = {}

        for r in raw_results:
            eid = int(r.eventId)
            if eid < lo or eid > hi:
                continue

            cid = int(r.counter)
            desc = desc_map.get(cid)
            if desc is None:
                continue

            value = _extract_counter_value(r, desc)
            cname = name_map.get(cid, "")

            samples.append(CounterSample(
                event_id=eid,
                counter_id=cid,
                counter_name=cname,
                value=value,
            ))

            per_counter.setdefault(cid, []).append((eid, value))

        # -- 计算 per-counter summaries -----------------------------------
        summaries: List[CounterSummary] = []
        for cid, pairs in per_counter.items():
            values = [v for _, v in pairs]
            if not values:
                continue

            min_val = min(values)
            max_val = max(values)
            mean_val = sum(values) / len(values)
            p95_val = _compute_p95(values)

            # Hotspot：该 counter 最大值对应的 event。
            hotspot_eid = max(pairs, key=lambda p: p[1])[0]

            summaries.append(CounterSummary(
                counter_name=name_map.get(cid, f"counter_{cid}"),
                min_val=min_val,
                max_val=max_val,
                mean_val=mean_val,
                p95_val=p95_val,
                hotspot_event_id=hotspot_eid,
            ))

        # -- 检测异常 events（任一 counter 的 z-score > 3）-----------------
        anomaly_event_set: set = set()
        for cid, pairs in per_counter.items():
            values = [v for _, v in pairs]
            if len(values) < 2:
                continue

            mean_val = sum(values) / len(values)
            std_val = _compute_std(values, mean_val)

            if std_val <= 0.0:
                continue

            threshold = mean_val + _ANOMALY_Z_THRESHOLD * std_val
            for eid, v in pairs:
                if v > threshold:
                    anomaly_event_set.add(eid)

        anomaly_events = sorted(anomaly_event_set)

        logger.info(
            "Sampled %d counters across events [%d, %d]: "
            "%d samples, %d summaries, %d anomaly events",
            len(counter_list), lo, hi,
            len(samples), len(summaries), len(anomaly_events),
        )

        return PerfResult(
            samples=samples,
            summaries=summaries,
            anomaly_events=anomaly_events,
        )

    # ------------------------------------------------------------------
    # detect_hotspots
    # ------------------------------------------------------------------

    async def detect_hotspots(
        self,
        session_id: str,
        session_manager: Any,
        *,
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """基于 GPU duration 识别 top-K 最昂贵的 events。

        Samples the ``EventGPUDuration`` counter (or its platform-specific
        equivalent) across all events in the capture, then returns the
        *top_k* slowest events sorted by descending duration.

        Parameters
        ----------
        session_id:
            活跃 session identifier。
        session_manager:
            提供 replay controller。
        top_k:
            返回的 hotspot 条目最大数量（默认 10）。

        Returns
        -------
        list[dict]
            每条包含：

            * ``event_id`` (``int``) -- the draw-call event ID.
            * ``duration_us`` (``float``) -- GPU duration in microseconds.
            * ``rank`` (``int``) -- 1-based rank (1 = slowest).

            Unavailable counters or a missing runtime raise errors. A successful empty read returns an empty list.
        """
        rd = _lazy_import_renderdoc()
        if rd is None:
            logger.warning("renderdoc unavailable; cannot detect hotspots")
            raise RuntimeError("GPU counter query unavailable")
        if top_k < 0:
            raise ValueError("top_k must be non-negative")

        try:
            controller = session_manager.get_controller(session_id)
        except Exception as exc:
            logger.warning(
                "Failed to get controller for session %s: %s",
                session_id, exc,
            )
            raise RuntimeError("GPU counter read failed") from exc

        # -- 查找 GPU-duration counter ------------------------------------
        try:
            all_counters = await self._offload(controller.EnumerateCounters)
        except Exception as exc:
            logger.error("EnumerateCounters failed: %s", exc)
            raise RuntimeError("GPU counter read failed") from exc

        duration_counter: Any = None
        duration_desc: Any = None

        for counter in all_counters:
            try:
                desc = await self._offload(
                    controller.DescribeCounter, counter,
                )
                cname = str(getattr(desc, "name", ""))
                # 检查 counter name 是否命中常见 GPU-duration 名称，
                # 同时检查 GPUCounter enum 成员名。
                enum_name = str(counter)
                if any(
                    dn.lower() in cname.lower() or dn.lower() in enum_name.lower()
                    for dn in _GPU_DURATION_NAMES
                ):
                    duration_counter = counter
                    duration_desc = desc
                    break
            except Exception:
                raise RuntimeError("GPU counter read failed") from None

        if duration_counter is None:
            logger.warning(
                "No GPU duration counter found among %d available counters",
                len(all_counters),
            )
            raise RuntimeError("GPU counter query unavailable")

        # -- 抓取所有 events 的 duration counter ---------------------------
        try:
            raw_results = await self._offload(
                controller.FetchCounters, [duration_counter],
            )
        except Exception as exc:
            logger.error("FetchCounters for GPU duration failed: %s", exc)
            raise RuntimeError("GPU counter read failed") from exc

        # -- 提取 (event_id, duration) 对 ---------------------------------
        event_durations: List[Tuple[int, float]] = []
        for r in raw_results:
            eid = int(r.eventId)
            value = _extract_counter_value(r, duration_desc)
            event_durations.append((eid, _duration_to_microseconds(value, duration_desc)))

        if not event_durations:
            logger.info("No duration samples returned; capture may be empty")
            return []

        # -- 递减排序并取 top-K -------------------------------------------
        event_durations.sort(key=lambda p: p[1], reverse=True)
        top = event_durations if top_k == 0 else event_durations[:top_k]

        hotspots: List[Dict[str, Any]] = []
        for rank, (eid, dur) in enumerate(top, start=1):
            hotspots.append({
                "event_id": eid,
                "duration_us": dur,
                "rank": rank,
            })

        logger.info(
            "Detected %d hotspot events (top_k=%d) in session %s; "
            "slowest event=%d (%.2f us)",
            len(hotspots), top_k, session_id,
            hotspots[0]["event_id"], hotspots[0]["duration_us"],
        )

        return hotspots
