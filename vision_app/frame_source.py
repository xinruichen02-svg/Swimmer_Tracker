from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class FrameSourceError(RuntimeError):
    """Raised when a video source cannot be opened or read."""


@dataclass(frozen=True)
class VideoSource:
    raw: str
    open_value: int | str
    offline_file: bool


@dataclass(frozen=True)
class FrameSample:
    image: Any
    timestamp: float
    width: int
    height: int


_SIGNED_INTEGER = re.compile(r"^[+-]?\d+$")


def parse_video_source(raw: str) -> VideoSource:
    if not isinstance(raw, str) or not raw.strip():
        raise FrameSourceError("摄像头源不能为空")
    source = raw.strip()
    if _SIGNED_INTEGER.fullmatch(source):
        index = int(source)
        if index < 0:
            raise FrameSourceError("摄像头索引不能为负数")
        return VideoSource(raw=source, open_value=index, offline_file=False)

    path = Path(source).expanduser()
    if path.exists():
        if not path.is_file():
            raise FrameSourceError("本地视频源必须是文件")
        return VideoSource(source, str(path.resolve()), True)
    if "://" not in source and (path.suffix or "\\" in source or "/" in source):
        raise FrameSourceError("填写的本地视频文件不存在")
    return VideoSource(source, source, False)


class FrameSource:
    """Layer 5: owns only video acquisition and its lifecycle."""

    def __init__(self, capture_factory=None) -> None:
        self._capture_factory = capture_factory
        self._capture = None
        self._source: VideoSource | None = None

    @property
    def is_open(self) -> bool:
        return bool(self._capture is not None and self._capture.isOpened())

    @property
    def source(self) -> VideoSource | None:
        return self._source

    def open(self, raw_source: str) -> FrameSample:
        source = parse_video_source(raw_source)
        self.close()
        factory = self._capture_factory
        if factory is None:
            import cv2

            factory = cv2.VideoCapture
        capture = factory(source.open_value)
        if not capture.isOpened():
            capture.release()
            raise FrameSourceError(f"无法打开摄像头源：{source.raw}")
        self._capture = capture
        self._source = source
        try:
            return self.read()
        except Exception:
            self.close()
            raise

    def read(self) -> FrameSample:
        if not self.is_open:
            raise FrameSourceError("摄像头未打开")
        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise FrameSourceError("摄像头断流或视频已经结束")
        height, width = frame.shape[:2]
        return FrameSample(frame, time.monotonic(), width, height)

    def close(self) -> None:
        capture = self._capture
        self._capture = None
        self._source = None
        if capture is not None:
            capture.release()

    @staticmethod
    def scan(max_index: int = 5, capture_factory=None) -> list[str]:
        if capture_factory is None:
            import cv2

            capture_factory = cv2.VideoCapture
        found: list[str] = []
        for index in range(max_index + 1):
            capture = capture_factory(index)
            try:
                if capture.isOpened():
                    ok, frame = capture.read()
                    if ok and frame is not None:
                        found.append(str(index))
            finally:
                capture.release()
        return found
