from __future__ import annotations

from dataclasses import dataclass
from vision_app.frame_source import FrameSample


class TargetTrackingError(RuntimeError):
    pass


class TargetSelectionCancelled(TargetTrackingError):
    pass


class TrackingLostError(TargetTrackingError):
    pass


@dataclass(frozen=True)
class TargetObservation:
    timestamp: float
    frame_width: int
    frame_height: int
    target_center_x: float
    target_center_y: float
    bbox: tuple[int, int, int, int]


def create_csrt_tracker():
    import cv2

    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    raise TargetTrackingError("当前 OpenCV 未提供 CSRT，请安装 opencv-contrib-python")


class TargetTracker:
    """Layer 3: owns ROI selection and CSRT state, but no control math."""

    def __init__(self, tracker_factory=None, roi_selector=None) -> None:
        self._tracker_factory = tracker_factory or create_csrt_tracker
        self._roi_selector = roi_selector
        self._tracker = None

    @property
    def locked(self) -> bool:
        return self._tracker is not None

    def select(self, sample: FrameSample, roi: tuple[int, int, int, int] | None = None) -> TargetObservation:
        if roi is None:
            selector = self._roi_selector
            if selector is None:
                import cv2

                roi = cv2.selectROI(
                    "手动框选游泳运动员，按 Enter 确认",
                    sample.image.copy(),
                    fromCenter=False,
                    showCrosshair=True,
                )
                cv2.destroyWindow("手动框选游泳运动员，按 Enter 确认")
            else:
                roi = selector(sample.image.copy())
        integer_roi = tuple(int(round(value)) for value in roi)
        if integer_roi == (0, 0, 0, 0):
            raise TargetSelectionCancelled("已取消目标框选")
        self._validate_bbox(integer_roi, sample.width, sample.height)
        tracker = self._tracker_factory()
        result = tracker.init(sample.image, integer_roi)
        if result is False:
            raise TargetTrackingError("CSRT 目标初始化失败")
        self._tracker = tracker
        return self._observation(sample, integer_roi)

    def update(self, sample: FrameSample) -> TargetObservation | None:
        if self._tracker is None:
            return None
        ok, bbox = self._tracker.update(sample.image)
        if not ok:
            self.clear()
            raise TrackingLostError("目标跟踪丢失，请停止后重新框选")
        integer_bbox = tuple(int(round(value)) for value in bbox)
        try:
            self._validate_bbox(integer_bbox, sample.width, sample.height, allow_partial=True)
        except TargetTrackingError as exc:
            self.clear()
            raise TrackingLostError("目标框已经离开画面") from exc
        return self._observation(sample, integer_bbox)

    def clear(self) -> None:
        self._tracker = None

    @staticmethod
    def _validate_bbox(bbox, width: int, height: int, allow_partial: bool = False) -> None:
        x, y, box_width, box_height = bbox
        valid = box_width > 0 and box_height > 0
        if allow_partial:
            valid = valid and x + box_width > 0 and y + box_height > 0 and x < width and y < height
        else:
            valid = valid and x >= 0 and y >= 0 and x + box_width <= width and y + box_height <= height
        if not valid:
            raise TargetTrackingError("目标框超出画面范围")

    @staticmethod
    def _observation(sample: FrameSample, bbox: tuple[int, int, int, int]) -> TargetObservation:
        x, y, width, height = bbox
        return TargetObservation(
            sample.timestamp,
            sample.width,
            sample.height,
            x + width / 2.0,
            y + height / 2.0,
            bbox,
        )
