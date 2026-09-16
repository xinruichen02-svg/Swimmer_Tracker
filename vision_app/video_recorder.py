from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class VideoRecorderError(RuntimeError):
    """Raised when a recording cannot be started or written."""


@dataclass(frozen=True)
class RecordingResult:
    path: Path
    frame_count: int


class VideoRecorder:
    """Owns an OpenCV VideoWriter and guarantees deterministic release."""

    def __init__(self, writer_factory: Callable[..., Any] | None = None) -> None:
        self._writer_factory = writer_factory
        self._writer = None
        self._path: Path | None = None
        self._frame_size: tuple[int, int] | None = None
        self._frame_count = 0

    @property
    def is_recording(self) -> bool:
        return self._writer is not None

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def frame_count(self) -> int:
        return self._frame_count

    def start(self, path: str | Path, frame_size: tuple[int, int], fps: float) -> Path:
        if self.is_recording:
            raise VideoRecorderError("录像已经在进行中")
        target = Path(path).expanduser()
        if not target.name:
            raise VideoRecorderError("录像保存文件不能为空")
        if target.suffix.lower() not in {".mp4", ".avi"}:
            target = target.with_suffix(".mp4")
        if not target.parent.exists() or not target.parent.is_dir():
            raise VideoRecorderError("录像保存目录不存在")
        width, height = frame_size
        if width <= 0 or height <= 0:
            raise VideoRecorderError("录像画面尺寸无效")
        if fps <= 0:
            raise VideoRecorderError("录像帧率必须大于 0")

        factory = self._writer_factory
        if factory is None:
            import cv2

            factory = cv2.VideoWriter
            codec_name = "XVID" if target.suffix.lower() == ".avi" else "mp4v"
            codec = cv2.VideoWriter_fourcc(*codec_name)
        else:
            codec = 0
        writer = factory(str(target.resolve()), codec, float(fps), (int(width), int(height)))
        if not writer.isOpened():
            writer.release()
            raise VideoRecorderError("无法创建录像文件，请更换保存位置或格式")
        self._writer = writer
        self._path = target.resolve()
        self._frame_size = (int(width), int(height))
        self._frame_count = 0
        return self._path

    def write(self, bgr_frame: Any) -> None:
        if not self.is_recording or self._frame_size is None:
            raise VideoRecorderError("录像尚未开始")
        try:
            height, width = bgr_frame.shape[:2]
        except (AttributeError, TypeError, ValueError) as exc:
            raise VideoRecorderError("录像帧格式无效") from exc
        if (width, height) != self._frame_size:
            raise VideoRecorderError(
                f"录像帧尺寸从 {self._frame_size[0]}x{self._frame_size[1]} "
                f"变为 {width}x{height}"
            )
        try:
            self._writer.write(bgr_frame)
        except Exception as exc:
            raise VideoRecorderError(f"写入录像失败：{exc}") from exc
        self._frame_count += 1

    def stop(self) -> RecordingResult | None:
        writer, path, frame_count = self._writer, self._path, self._frame_count
        self._writer = None
        self._path = None
        self._frame_size = None
        self._frame_count = 0
        if writer is None or path is None:
            return None
        writer.release()
        return RecordingResult(path, frame_count)
