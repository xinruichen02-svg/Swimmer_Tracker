from __future__ import annotations

import math
from dataclasses import dataclass

from vision_app.frame_source import FrameSample


@dataclass(frozen=True)
class FrameProcessingConfig:
    """Conservative defaults for a real-time underwater video pipeline."""

    max_width: int = 640
    max_height: int = 360
    statistics_width: int = 320
    target_guard_fraction: float = 0.30
    gain_smoothing: float = 0.10
    statistics_interval: int = 4
    background_blur_sigma: float = 2.20
    background_blur_mix: float = 0.65
    guard_blur_sigma: float = 0.70
    mask_feather_fraction: float = 0.06
    roi_clahe_max_clip: float = 2.60


class FrameProcessor:
    """Lightweight adaptive enhancement for tracking and presentation.

    ``prepare`` creates the unenhanced, stable-resolution frame used for manual
    target selection.  Once a box exists, ``process`` estimates colour gains
    outside its guard area and creates a three-zone tracking frame: sharpened
    target, lightly blurred guard ring and suppressed far background.  This
    tracking frame must be passed to CSRT for both initialization and updates.
    """

    def __init__(self, config: FrameProcessingConfig | None = None) -> None:
        self.config = config or FrameProcessingConfig()
        self._smoothed_gains = None
        self._frame_index = 0

    def reset(self) -> None:
        """Forget colour statistics when a different video source is opened."""

        self._smoothed_gains = None
        self._frame_index = 0

    def prepare(self, sample: FrameSample) -> FrameSample:
        """Return an unenhanced frame in the fixed tracking coordinate space."""

        image = sample.image
        if not self._is_bgr_image(image):
            return sample
        import cv2

        image = self._resize_for_processing(image, cv2)
        height, width = image.shape[:2]
        return FrameSample(image, sample.timestamp, width, height)

    def process(
        self,
        sample: FrameSample,
        target_bbox: tuple[int, int, int, int] | None = None,
        *,
        enhance: bool = True,
    ) -> FrameSample:
        """Prepare a stable frame for tracking.

        Non-array test doubles are intentionally passed through unchanged.
        """

        prepared = self.prepare(sample)
        image = prepared.image
        if not self._is_bgr_image(image) or not enhance or target_bbox is None:
            return prepared

        import cv2
        import numpy as np

        height, width = image.shape[:2]
        # ``target_bbox`` comes from the preceding processed frame, so it is
        # already expressed in this stable working-resolution coordinate space.
        interval = max(1, int(self.config.statistics_interval))
        if self._smoothed_gains is None or self._frame_index % interval == 0:
            gains = self._estimate_background_gains(image, target_bbox, cv2)
        else:
            gains = self._smoothed_gains
        self._frame_index += 1
        image = self._apply_gains(image, gains)
        image = self._layered_tracking_image(image, target_bbox, cv2, np)
        return FrameSample(image, sample.timestamp, width, height)

    def _layered_tracking_image(self, image, target_bbox, cv2, np):
        clipped = self._clip_bbox(target_bbox, image.shape[1], image.shape[0])
        if clipped is None:
            return image
        x, y, box_width, box_height = clipped

        target_diagonal = math.hypot(box_width, box_height)
        sigma_background = float(np.clip(
            max(self.config.background_blur_sigma, target_diagonal / 120.0), 1.5, 3.0
        ))
        blurred_background = cv2.GaussianBlur(image, (0, 0), sigma_background)
        mix = float(np.clip(self.config.background_blur_mix, 0.0, 0.85))
        output = cv2.addWeighted(image, 1.0 - mix, blurred_background, mix, 0.0)

        guard_x = max(4, int(round(box_width * self.config.target_guard_fraction)))
        guard_y = max(4, int(round(box_height * self.config.target_guard_fraction)))
        left, top = max(0, x - guard_x), max(0, y - guard_y)
        right = min(image.shape[1], x + box_width + guard_x)
        bottom = min(image.shape[0], y + box_height + guard_y)
        guard_blurred = cv2.GaussianBlur(image, (0, 0), self.config.guard_blur_sigma)
        guard_bounds = (left, top, right - left, bottom - top)
        guard_layer = guard_blurred[top:bottom, left:right]
        self._blend_region(
            output, guard_layer, guard_bounds,
            self._feather_width(guard_bounds[2], guard_bounds[3]), np,
        )

        target_roi = image[y:y + box_height, x:x + box_width].copy()
        target_layer = self._adaptive_roi(target_roi, cv2, np)
        self._blend_region(
            output, target_layer, clipped,
            self._feather_width(box_width, box_height), np,
        )
        return output

    def _feather_width(self, width: int, height: int) -> int:
        return max(3, min(16, int(round(min(width, height) * self.config.mask_feather_fraction))))

    @staticmethod
    def _blend_region(output, layer, bounds, feather: int, np) -> None:
        left, top, width, height = bounds
        if width <= 0 or height <= 0:
            return
        yy, xx = np.ogrid[:height, :width]
        edge_distance = np.minimum.reduce([
            np.broadcast_to(xx, (height, width)),
            np.broadcast_to(width - 1 - xx, (height, width)),
            np.broadcast_to(yy, (height, width)),
            np.broadcast_to(height - 1 - yy, (height, width)),
        ])
        alpha = np.clip((edge_distance + 1.0) / float(max(1, feather)), 0.0, 1.0)[..., None]
        base = output[top:top + height, left:left + width].astype(np.float32)
        source = layer.astype(np.float32)
        output[top:top + height, left:left + width] = np.clip(
            base * (1.0 - alpha) + source * alpha, 0, 255
        ).astype(np.uint8)

    @staticmethod
    def _is_bgr_image(image) -> bool:
        return bool(
            hasattr(image, "shape")
            and len(image.shape) == 3
            and image.shape[2] == 3
            and hasattr(image, "dtype")
        )

    def _resize_for_processing(self, image, cv2):
        height, width = image.shape[:2]
        scale = min(
            1.0,
            self.config.max_width / float(width),
            self.config.max_height / float(height),
        )
        if scale >= 0.999:
            return image.copy()
        size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
        return cv2.resize(image, size, interpolation=cv2.INTER_AREA)

    def _estimate_background_gains(self, image, target_bbox, cv2):
        import numpy as np

        height, width = image.shape[:2]
        scale = min(1.0, self.config.statistics_width / float(width))
        if scale < 0.999:
            stat_width = max(1, int(round(width * scale)))
            stat_height = max(1, int(round(height * scale)))
            statistics_image = cv2.resize(
                image, (stat_width, stat_height), interpolation=cv2.INTER_AREA
            )
        else:
            statistics_image = image
            stat_height, stat_width = height, width

        mask = np.ones((stat_height, stat_width), dtype=bool)
        if target_bbox is not None:
            x, y, box_width, box_height = target_bbox
            guard_x = int(round(box_width * self.config.target_guard_fraction))
            guard_y = int(round(box_height * self.config.target_guard_fraction))
            x0 = max(0, int(round((x - guard_x) * stat_width / width)))
            y0 = max(0, int(round((y - guard_y) * stat_height / height)))
            x1 = min(stat_width, int(round((x + box_width + guard_x) * stat_width / width)))
            y1 = min(stat_height, int(round((y + box_height + guard_y) * stat_height / height)))
            if x1 > x0 and y1 > y0:
                mask[y0:y1, x0:x1] = False

        pixels = statistics_image[mask]
        if pixels.shape[0] < 64:
            pixels = statistics_image.reshape(-1, 3)
        luminance = pixels.mean(axis=1)
        low, high = np.percentile(luminance, (5.0, 95.0))
        valid = (luminance >= low) & (luminance <= high)
        # Bright, nearly neutral points are usually bubbles or specular glare.
        channel_spread = pixels.max(axis=1) - pixels.min(axis=1)
        valid &= ~((luminance > 205.0) & (channel_spread < 24))
        filtered = pixels[valid]
        if filtered.shape[0] < 64:
            filtered = pixels

        means = np.maximum(filtered.astype(np.float32).mean(axis=0), 1.0)
        neutral = float(np.cbrt(means[0] * means[1] * means[2]))
        measured = neutral / means
        # BGR bounds allow more red recovery without turning blue water orange.
        measured = np.clip(
            measured, [0.80, 0.85, 0.90], [1.15, 1.20, 1.45]
        ).astype(np.float32)
        if self._smoothed_gains is None:
            self._smoothed_gains = measured
        else:
            rate = self.config.gain_smoothing
            candidate = (1.0 - rate) * self._smoothed_gains + rate * measured
            self._smoothed_gains = self._smoothed_gains + np.clip(
                candidate - self._smoothed_gains, -0.02, 0.02
            )
        return self._smoothed_gains

    @staticmethod
    def _apply_gains(image, gains):
        import numpy as np

        corrected = image.astype(np.float32) * gains.reshape(1, 1, 3)
        return np.clip(corrected, 0, 255).astype(np.uint8)

    def _adaptive_roi(self, roi, cv2, np):
        lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
        lightness, a_channel, b_channel = cv2.split(lab)
        p05, median, p95 = np.percentile(lightness, (5.0, 50.0, 95.0))
        dynamic_range = float(p95 - p05)

        adjusted = lightness
        if 2.0 < median < 105.0:
            desired = 112.0 / 255.0
            gamma = math.log(desired) / math.log(max(median / 255.0, 1e-3))
            gamma = float(np.clip(gamma, 0.75, 1.0))
            lookup = np.clip(
                (np.arange(256) / 255.0) ** gamma * 255.0, 0, 255
            ).astype(np.uint8)
            adjusted = cv2.LUT(adjusted, lookup)

        if dynamic_range < 90.0:
            strength = (90.0 - dynamic_range) / 90.0
            clip_limit = 1.20 + strength * (self.config.roi_clahe_max_clip - 1.20)
            adjusted = cv2.createCLAHE(
                clipLimit=clip_limit, tileGridSize=(6, 6)
            ).apply(adjusted)

        laplacian = cv2.Laplacian(adjusted, cv2.CV_32F)
        sharpness = float(laplacian.var())
        channel_spread = (
            roi.max(axis=2).astype(np.int16) - roi.min(axis=2).astype(np.int16)
        )
        bright_neutral = (adjusted > max(205.0, p95)) & (channel_spread < 28)
        edge_pixels = np.abs(laplacian) > 20.0
        bubble_score = float(np.mean(bright_neutral) * np.mean(edge_pixels))

        amount = 0.0
        if sharpness < 80.0:
            amount = 0.35
        elif sharpness < 160.0:
            amount = 0.20
        if bubble_score > 0.010:
            amount *= 0.35
        if float(np.mean(bright_neutral)) > 0.08:
            amount = 0.0
        if amount > 0.0:
            blurred = cv2.GaussianBlur(adjusted, (0, 0), 1.1)
            adjusted = cv2.addWeighted(
                adjusted, 1.0 + amount, blurred, -amount, 0
            )

        return cv2.cvtColor(
            cv2.merge((adjusted, a_channel, b_channel)), cv2.COLOR_LAB2BGR
        )

    @staticmethod
    def _clip_bbox(bbox, width: int, height: int):
        x, y, box_width, box_height = (int(round(value)) for value in bbox)
        left, top = max(0, x), max(0, y)
        right, bottom = min(width, x + box_width), min(height, y + box_height)
        if right <= left or bottom <= top:
            return None
        return left, top, right - left, bottom - top
