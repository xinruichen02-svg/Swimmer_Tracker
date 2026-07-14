from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path

import cv2


class VisionInputError(ValueError):
    """Raised when a camera source or target selection is invalid."""


class VisionRuntimeError(RuntimeError):
    """Raised when frames cannot be acquired or processed."""


class TrackingLostError(VisionRuntimeError):
    """Raised once when the active target can no longer be tracked."""


class TargetSelectionCancelled(VisionInputError):
    """Raised when the user cancels manual ROI selection."""


@dataclass(frozen=True)
class VideoSource:
    raw: str
    open_value: int | str
    offline_file: bool


@dataclass(frozen=True)
class TrackingMeasurement:
    timestamp: float
    frame_width: int
    frame_height: int
    target_center_x: float
    target_center_y: float
    offset_px: float
    bbox: tuple[int, int, int, int]


_SIGNED_INTEGER = re.compile(r"^[+-]?\d+$")


def parse_video_source(raw: str) -> VideoSource:
    if not isinstance(raw, str) or not raw.strip():
        raise VisionInputError("摄像头源不能为空")
    source = raw.strip()
    if _SIGNED_INTEGER.fullmatch(source):
        camera_index = int(source)
        if camera_index < 0:
            raise VisionInputError("摄像头索引不能为负数")
        return VideoSource(raw=source, open_value=camera_index, offline_file=False)

    path = Path(source).expanduser()
    if path.exists():
        if not path.is_file():
            raise VisionInputError("本地视频源必须是文件")
        resolved = str(path.resolve())
        return VideoSource(raw=source, open_value=resolved, offline_file=True)

    if "://" not in source and (path.suffix or "\\" in source or "/" in source):
        raise VisionInputError("填写的本地视频文件不存在")
    return VideoSource(raw=source, open_value=source, offline_file=False)


def create_csrt_tracker():
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    raise VisionRuntimeError("当前 OpenCV 未提供 CSRT，请安装 opencv-contrib-python")


def _center(bbox: tuple[int, int, int, int]) -> tuple[float, float]:
    x, y, width, height = bbox
    return x + width / 2.0, y + height / 2.0


class VisionTracker:
    def __init__(self) -> None:
        self._capture = None
        self._tracker = None
        self._last_frame = None
        self._source: VideoSource | None = None
        self._last_bbox: tuple[int, int, int, int] | None = None

    @property
    def is_open(self) -> bool:
        capture = self._capture
        return bool(capture is not None and capture.isOpened())

    @property
    def target_locked(self) -> bool:
        return self._tracker is not None

    @property
    def source(self) -> VideoSource | None:
        return self._source

    @property
    def last_frame(self):
        return None if self._last_frame is None else self._last_frame.copy()

    def open(self, raw_source: str):
        source = parse_video_source(raw_source)
        self.release()
        capture = cv2.VideoCapture(source.open_value)
        if not capture.isOpened():
            capture.release()
            raise VisionRuntimeError(f"无法打开摄像头源：{source.raw}")
        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            raise VisionRuntimeError("摄像头已打开，但无法读取首帧")
        self._capture = capture
        self._source = source
        self._last_frame = frame
        self._tracker = None
        self._last_bbox = None
        return frame.copy()

    def select_target(self) -> TrackingMeasurement:
        if self._last_frame is None:
            raise VisionInputError("请先打开摄像头")
        selection_frame = self._last_frame.copy()
        bbox = cv2.selectROI("手动框选游泳运动员，按 Enter 确认", selection_frame, fromCenter=False, showCrosshair=True)
        cv2.destroyWindow("手动框选游泳运动员，按 Enter 确认")
        integer_bbox = tuple(int(value) for value in bbox)
        if integer_bbox == (0, 0, 0, 0):
            raise TargetSelectionCancelled("已取消目标框选")
        x, y, width, height = integer_bbox
        frame_height, frame_width = selection_frame.shape[:2]
        if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > frame_width or y + height > frame_height:
            raise VisionInputError("目标框超出画面范围")

        tracker = create_csrt_tracker()
        init_result = tracker.init(selection_frame, integer_bbox)
        if init_result is False:
            raise VisionRuntimeError("CSRT 目标初始化失败")
        self._tracker = tracker
        self._last_bbox = integer_bbox
        return self._measurement(integer_bbox, time.monotonic(), frame_width, frame_height)

    def read(self) -> tuple[object, TrackingMeasurement | None]:
        capture = self._capture
        if capture is None or not capture.isOpened():
            raise VisionRuntimeError("摄像头未打开")
        ok, frame = capture.read()
        if not ok or frame is None:
            raise VisionRuntimeError("摄像头断流或视频已经结束")
        self._last_frame = frame
        tracker = self._tracker
        if tracker is None:
            return frame.copy(), None
        tracking_ok, bbox = tracker.update(frame)
        if not tracking_ok:
            self.clear_target()
            raise TrackingLostError("目标跟踪丢失，请停止后重新框选")
        integer_bbox = tuple(int(round(value)) for value in bbox)
        x, y, width, height = integer_bbox
        frame_height, frame_width = frame.shape[:2]
        if width <= 0 or height <= 0 or x + width <= 0 or y + height <= 0 or x >= frame_width or y >= frame_height:
            self.clear_target()
            raise TrackingLostError("目标框已经离开画面")
        self._last_bbox = integer_bbox
        measurement = self._measurement(integer_bbox, time.monotonic(), frame_width, frame_height)
        return frame.copy(), measurement

    @staticmethod
    def _measurement(
        bbox: tuple[int, int, int, int],
        timestamp: float,
        frame_width: int,
        frame_height: int,
    ) -> TrackingMeasurement:
        center_x, center_y = _center(bbox)
        return TrackingMeasurement(
            timestamp=timestamp,
            frame_width=frame_width,
            frame_height=frame_height,
            target_center_x=center_x,
            target_center_y=center_y,
            offset_px=center_x - frame_width / 2.0,
            bbox=bbox,
        )

    def annotate(
        self,
        frame,
        measurement: TrackingMeasurement | None,
        *,
        max_offset_fraction: float = 0.45,
    ):
        annotated = frame.copy()
        height, width = annotated.shape[:2]
        center_x = width // 2
        center_y = height // 2
        limit = int(width * max_offset_fraction)
        left_limit = max(0, center_x - limit)
        right_limit = min(width - 1, center_x + limit)
        cv2.rectangle(annotated, (left_limit, 0), (right_limit, height - 1), (60, 85, 60), 1)
        cv2.line(annotated, (0, center_y), (width - 1, center_y), (255, 255, 255), 1)
        cv2.line(annotated, (center_x, 0), (center_x, height - 1), (255, 255, 255), 1)
        if measurement is not None:
            x, y, box_width, box_height = measurement.bbox
            cv2.rectangle(annotated, (x, y), (x + box_width, y + box_height), (30, 207, 149), 2)
            target = (int(round(measurement.target_center_x)), int(round(measurement.target_center_y)))
            cv2.circle(annotated, target, 5, (35, 78, 255), -1)
            cv2.line(annotated, (center_x, center_y), target, (14, 113, 255), 2)
            cv2.putText(
                annotated,
                f"offset {measurement.offset_px:+.1f}px",
                (14, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
            )
        else:
            cv2.putText(
                annotated,
                "Select swimmer target",
                (14, 28),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.65,
                (255, 255, 255),
                2,
            )
        return annotated

    def clear_target(self) -> None:
        self._tracker = None
        self._last_bbox = None

    def release(self) -> None:
        capture = self._capture
        self._capture = None
        if capture is not None:
            capture.release()
        self._tracker = None
        self._last_bbox = None
        self._last_frame = None
        self._source = None
        cv2.destroyAllWindows()
