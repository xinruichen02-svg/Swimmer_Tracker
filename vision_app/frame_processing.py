from __future__ import annotations

from vision_app.frame_source import FrameSample


class FrameProcessor:
    """Layer 4 extension point. V1 intentionally performs no processing."""

    def process(self, sample: FrameSample) -> FrameSample:
        return sample
