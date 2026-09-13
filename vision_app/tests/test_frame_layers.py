import unittest

from vision_app.frame_processing import FrameProcessor
from vision_app.frame_source import FrameSample
from vision_app.target_tracking import TargetTracker, TrackingLostError


class FakeFrame:
    shape = (100, 200, 3)
    def copy(self): return self


class FakeTracker:
    def __init__(self): self.responses = [(True, (20, 10, 30, 20)), (False, ())]
    def init(self, _frame, _roi): return True
    def update(self, _frame): return self.responses.pop(0)


class FrameLayerTests(unittest.TestCase):
    def test_identity_processor_preserves_sample_and_image(self):
        sample = FrameSample(FakeFrame(), 1.0, 200, 100)
        self.assertIs(FrameProcessor().process(sample), sample)

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
