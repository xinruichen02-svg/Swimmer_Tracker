import unittest

import numpy as np

from vision_app.frame_processing import FrameProcessingConfig, FrameProcessor
from vision_app.frame_source import FrameSample, FrameSource
from vision_app.target_tracking import TargetTracker, TrackingLostError


class FakeFrame:
    shape = (100, 200, 3)
    def copy(self): return self


class FakeCapture:
    def __init__(self):
        self.frame = FakeFrame()
        self.grabbed = 0
        self.released = False

    def isOpened(self): return not self.released
    def read(self): return True, self.frame
    def grab(self):
        self.grabbed += 1
        return self.grabbed <= 2
    def get(self, _property): return 25.0
    def release(self): self.released = True


class FakeTracker:
    def __init__(self):
        self.responses = [(True, (20, 10, 30, 20)), (False, ())]
        self.initial_frame = None
    def init(self, frame, _roi):
        self.initial_frame = frame
        return True
    def update(self, _frame): return self.responses.pop(0)


class FrameLayerTests(unittest.TestCase):
    def test_source_fps_and_late_frame_skip(self):
        capture = FakeCapture()
        source = FrameSource(capture_factory=lambda _value: capture)
        source.open("0")
        self.assertEqual(source.fps, 25.0)
        self.assertEqual(source.skip_frames(5), 2)
        source.close()
        self.assertTrue(capture.released)

    def test_identity_processor_preserves_sample_and_image(self):
        sample = FrameSample(FakeFrame(), 1.0, 200, 100)
        self.assertIs(FrameProcessor().process(sample), sample)

    def test_processor_downsizes_and_updates_sample_dimensions(self):
        image = np.full((200, 400, 3), (160, 120, 70), dtype=np.uint8)
        processor = FrameProcessor(FrameProcessingConfig(max_width=200, max_height=100))
        result = processor.process(FrameSample(image, 1.0, 400, 200))
        self.assertEqual(result.image.shape, (100, 200, 3))
        self.assertEqual((result.width, result.height), (200, 100))
        self.assertEqual(result.timestamp, 1.0)

    def test_processing_can_be_disabled_for_raw_control_group(self):
        image = np.full((200, 400, 3), (160, 120, 70), dtype=np.uint8)
        processor = FrameProcessor(FrameProcessingConfig(max_width=200, max_height=100))
        sample = FrameSample(image, 1.0, 400, 200)
        result = processor.process(sample, enhance=False)
        import cv2
        expected = cv2.resize(image, (200, 100), interpolation=cv2.INTER_AREA)
        np.testing.assert_array_equal(result.image, expected)

    def test_layered_frame_is_built_before_tracking(self):
        yy, xx = np.indices((120, 200))
        texture = ((xx * 17 + yy * 11) % 90).astype(np.uint8)
        image = np.dstack((texture + 90, texture + 70, texture + 45))
        image[40:80, 70:130] = np.where(
            ((xx[40:80, 70:130] // 4) % 2)[..., None],
            np.array((65, 90, 150), dtype=np.uint8),
            np.array((105, 135, 200), dtype=np.uint8),
        )
        sample = FrameSample(image, 2.0, 200, 120)
        result = FrameProcessor().process(sample, (70, 40, 60, 40))
        self.assertFalse(np.array_equal(result.image[5:30, 5:50], image[5:30, 5:50]))
        self.assertFalse(np.array_equal(result.image[48:72, 82:118], image[48:72, 82:118]))
        self.assertEqual((result.timestamp, result.width, result.height), (2.0, 200, 120))

    def test_tracker_outputs_observation_and_reports_loss(self):
        fake = FakeTracker()
        tracker = TargetTracker(tracker_factory=lambda: fake)
        sample = FrameSample(FakeFrame(), 1.0, 200, 100)
        selected = tracker.select(sample, (10, 10, 20, 20))
        self.assertEqual(selected.target_center_x, 20)
        updated = tracker.update(FrameSample(FakeFrame(), 2.0, 200, 100))
        self.assertEqual(updated.target_center_x, 35)
        with self.assertRaises(TrackingLostError):
            tracker.update(FrameSample(FakeFrame(), 3.0, 200, 100))
        self.assertFalse(tracker.locked)

    def test_manual_box_can_initialize_csrt_on_layered_frame(self):
        image = np.full((120, 200, 3), (150, 105, 65), dtype=np.uint8)
        image[40:80, 70:130] = (70, 110, 180)
        raw = FrameSample(image, 1.0, 200, 120)
        fake = FakeTracker()
        tracker = TargetTracker(tracker_factory=lambda: fake)
        bbox = tracker.select_bbox(raw, (70, 40, 60, 40))
        layered = FrameProcessor().process(raw, bbox)
        tracker.initialize(layered, bbox)
        self.assertIs(fake.initial_frame, layered.image)
        self.assertFalse(np.array_equal(layered.image, raw.image))
