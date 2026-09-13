from __future__ import annotations

from vision_app.frame_source import FrameSample
from vision_app.target_tracking import TargetObservation


class FrameRenderer:
    """Presentation-only overlays; output is never fed back into tracking."""

    def render(self, sample: FrameSample, observation: TargetObservation | None, *, target_offset_px: float = 0.0, max_offset_fraction: float = 0.45):
        import cv2

        image = sample.image.copy()
        center_x = int(round(sample.width / 2.0 + target_offset_px))
        center_y = sample.height // 2
        limit = int(sample.width * max_offset_fraction)
        cv2.rectangle(image, (max(0, center_x - limit), 0), (min(sample.width - 1, center_x + limit), sample.height - 1), (60, 85, 60), 1)
        cv2.line(image, (center_x, 0), (center_x, sample.height - 1), (255, 255, 255), 1)
        cv2.line(image, (0, center_y), (sample.width - 1, center_y), (255, 255, 255), 1)
        if observation is not None:
            x, y, width, height = observation.bbox
            target = (int(round(observation.target_center_x)), int(round(observation.target_center_y)))
            cv2.rectangle(image, (x, y), (x + width, y + height), (30, 207, 149), 2)
            cv2.circle(image, target, 5, (35, 78, 255), -1)
            cv2.line(image, (center_x, center_y), target, (14, 113, 255), 2)
        return image
