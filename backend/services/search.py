# 检索入口：检查类别/时间等查询条件，再让数据库查已有索引。
# 这里不读视频、不加载 YOLO，所以分析一次后可以反复查询。

from backend.database.repository import IndexRepository
import math


class SearchService:
    def __init__(self, repository: IndexRepository):
        self.repository = repository

    def search(self, class_name: str | None, video_id: int | None = None, start_time=None, end_time=None,
               *, include_counts=False):
        if class_name is not None:
            class_name = class_name.strip().lower()
            if not class_name:
                raise ValueError("目标类别不能为空")
        if video_id is not None and video_id <= 0:
            raise ValueError("video_id 必须大于 0")
        for value in (start_time, end_time):
            if value is not None and (not math.isfinite(value) or value < 0):
                raise ValueError("查询时间必须为有限非负数")
        if start_time is not None and end_time is not None and end_time < start_time:
            raise ValueError("end_time 不能早于 start_time")
        return self.repository.search(class_name, video_id, start_time, end_time, include_counts=include_counts)
