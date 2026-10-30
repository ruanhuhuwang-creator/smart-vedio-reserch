# 时间段合并工具：只判断某类别是否连续出现，不识别是不是同一个人。
# 例如 person 在 120、120.5、121 秒出现，可合并为 [120,121]；不推测间隙里的真实人数。

"""Category presence events, without tracking identities or assuming truth."""
from dataclasses import dataclass
import math
from typing import Iterable


@dataclass(frozen=True)
class Event:
    class_name: str
    start_time: float
    end_time: float
    sample_count: int


def merge_observations(observations: Iterable, *, duration: float, merge_gap: float = 1.0,
                       min_samples: int = 2) -> Iterable[Event]:
    """Input must be sorted by (category, timestamp); output streams one cluster.

    Boundaries are first/last observed PTS, with no speculative extension.
    Repeated detections at one timestamp count once; singleton clusters are dropped.
    """
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("视频时长必须为有限非负数")
    if not math.isfinite(merge_gap) or merge_gap < 0 or min_samples < 2:
        raise ValueError("合并间隔必须非负且 min_samples 至少为 2")
    category = None
    start = end = 0.0
    count = 0
    # count 数的是不同采样时刻，不是人数；同一帧 5 个人只算一次“该类别出现”。
    previous_key = None
    for row in observations:
        name, timestamp = row[0], float(row[1])
        if not math.isfinite(timestamp) or timestamp < 0:
            raise ValueError("检测时间戳无效")
        key = (name, timestamp)
        if previous_key is not None and key < previous_key:
            raise ValueError("检测记录必须按类别、时间排序")
        previous_key = key
        if timestamp > duration + 1e-6:
            continue
        timestamp = min(duration, timestamp)
        # 换了类别，或距离上次出现太久，就结算上一段，另起一段。
        # 1e-6 是浮点误差余量，避免本来相等的边界因小数误差被拆开。
        if name != category or timestamp - end > merge_gap + 1e-6:
            if count >= min_samples:
                yield Event(category, start, end, count)
            category, start, end, count = name, timestamp, timestamp, 1
        elif timestamp > end + 1e-7:
            end = timestamp
            count += 1
    if count >= min_samples:
        yield Event(category, start, end, count)
