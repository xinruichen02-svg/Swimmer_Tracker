import unittest

from vision_app.safety import AppState, SafetyController, SafetyInputs, StateTransitionError


def ready_inputs(**overrides):
    values = dict(
        serial_connected=True,
        telemetry_fresh=True,
        camera_ready=True,
        target_locked=True,
        calibration_confirmed=True,
        directions_valid=True,
        motion_solution_valid=True,
        offline_source=False,
    )
    values.update(overrides)
    return SafetyInputs(**values)


class StartBlockerTests(unittest.TestCase):
    def test_ready_inputs_have_no_blockers(self):
        self.assertEqual(ready_inputs().start_blockers(), ())

    def test_all_missing_conditions_are_reported(self):
        inputs = SafetyInputs()
        blockers = inputs.start_blockers()
        self.assertIn("电机后端未连接", blockers)
        self.assertIn("尚未收到新鲜电机反馈", blockers)
        self.assertIn("摄像头未就绪", blockers)
        self.assertIn("尚未框选并锁定运动员", blockers)
        self.assertIn("换算值尚未确认", blockers)
        self.assertIn("方向配置无效", blockers)
        self.assertIn("运动解算尚未就绪", blockers)

    def test_offline_video_blocks_real_motor_start(self):
        blockers = ready_inputs(offline_source=True).start_blockers()
        self.assertIn("离线视频禁止启动真实电机", blockers)

    def test_offline_video_is_allowed_in_virtual_mode(self):
        self.assertEqual(ready_inputs(offline_source=True, real_backend=False).start_blockers(), ())

    def test_constant_speed_does_not_require_camera_or_target(self):
        inputs = ready_inputs(
            camera_ready=False,
            target_locked=False,
            motion_solution_valid=False,
            offline_source=True,
        )
        self.assertEqual(inputs.constant_speed_blockers(), ())


class SafetyControllerTests(unittest.TestCase):
    def test_normal_path_and_manual_stop(self):
        controller = SafetyController()
        controller.serial_connected()
        self.assertEqual(controller.state, AppState.STOPPED)
        controller.camera_opened()
        controller.target_locked()
        controller.start(ready_inputs())
        self.assertEqual(controller.state, AppState.RUNNING)
        self.assertTrue(controller.manual_stop())
        self.assertEqual(controller.state, AppState.STOPPED)

    def test_start_is_rejected_when_any_blocker_exists(self):
        controller = SafetyController()
        controller.serial_connected()
        controller.camera_opened()
        controller.target_locked()
        with self.assertRaises(StateTransitionError):
            controller.start(ready_inputs(telemetry_fresh=False))

    def test_constant_speed_starts_from_stopped_without_camera(self):
        controller = SafetyController()
        controller.serial_connected()
        controller.start_constant_speed(
            ready_inputs(camera_ready=False, target_locked=False, motion_solution_valid=False)
        )
        self.assertEqual(controller.state, AppState.RUNNING)
        self.assertTrue(controller.manual_stop())
        self.assertEqual(controller.state, AppState.STOPPED)

    def test_camera_close_returns_to_stopped(self):
        controller = SafetyController()
        controller.serial_connected()
        controller.camera_opened()
        controller.target_locked()
        controller.camera_closed()
        self.assertEqual(controller.state, AppState.STOPPED)

    def test_fault_is_latched_and_stop_request_is_idempotent(self):
        controller = SafetyController()
        controller.serial_connected()
        controller.camera_opened()
        controller.target_locked()
        controller.start(ready_inputs())

        self.assertTrue(controller.fault("跟踪丢失"))
        self.assertFalse(controller.fault("串口异常"))
        self.assertEqual(controller.state, AppState.FAULT)
        self.assertEqual(controller.fault_reason, "跟踪丢失")
        self.assertTrue(controller.consume_stop_request())
        self.assertFalse(controller.consume_stop_request())

        self.assertTrue(controller.manual_stop())
        self.assertEqual(controller.state, AppState.FAULT)
        self.assertEqual(controller.fault_reason, "跟踪丢失")

        controller.acknowledge_fault()
        self.assertEqual(controller.state, AppState.STOPPED)
        self.assertIsNone(controller.fault_reason)

    def test_disconnect_never_restores_running_state(self):
        controller = SafetyController()
        controller.serial_connected()
        controller.camera_opened()
        controller.target_locked()
        controller.start(ready_inputs())
        controller.disconnected("USB断开")
        self.assertEqual(controller.state, AppState.DISCONNECTED)
        self.assertNotEqual(controller.state, AppState.RUNNING)


if __name__ == "__main__":
    unittest.main()
