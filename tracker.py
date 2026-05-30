import time
from dataclasses import dataclass, field


@dataclass
class SwimPID:
    """
    PID controller for the swimming tracker.

    robot_speed:
        Speed read from the robot itself.

    center_offset_speed:
        Speed caused by the target drifting away from / toward the frame center.
        This should come from swimming_app.py. Prefer a signed speed on the
        control axis, not only math.hypot(...), otherwise direction is lost.

    estimated_target_speed = robot_speed + center_offset_speed
    expected_robot_speed is the speed command that should be sent to the motor.
    """

    kp: float
    ki: float
    kd: float
    feedforward: float = 1.0
    output_min: float | None = None
    output_max: float | None = None
    integral_min: float | None = None
    integral_max: float | None = None

    _integral: float = field(default=0.0, init=False)
    _last_error: float = field(default=0.0, init=False)
    _last_time: float | None = field(default=None, init=False)
    _last_output: float = field(default=0.0, init=False)
    _initialized: bool = field(default=False, init=False)

    def reset(self) -> None:
        self._integral = 0.0
        self._last_error = 0.0
        self._last_time = None
        self._last_output = 0.0
        self._initialized = False

    def update(
        self,
        robot_speed: float,
        center_offset_speed: float,
        dt: float | None = None,
    ) -> float:
        """
        Return expected robot speed.

        If the target is moving relative to the frame center, the robot should
        compensate for that relative speed. The PID error is therefore the
        difference between estimated target speed and current robot speed.
        """
        if dt is None:
            now = time.monotonic()
            if self._last_time is None:
                self._last_time = now
                dt = 0.0
            else:
                dt = now - self._last_time
                self._last_time = now

        dt = max(dt, 1e-6)

        estimated_target_speed = robot_speed + center_offset_speed
        error = estimated_target_speed - robot_speed

        self._integral += error * dt
        self._integral = self._clamp_integral(self._integral)
        derivative = 0.0 if not self._initialized else (error - self._last_error) / dt

        correction = self.kp * error + self.ki * self._integral + self.kd * derivative
        expected_robot_speed = robot_speed + self.feedforward * center_offset_speed + correction
        expected_robot_speed = self._clamp_output(expected_robot_speed)

        self._last_error = error
        self._last_output = expected_robot_speed
        self._initialized = True
        return expected_robot_speed

    def _clamp_output(self, value: float) -> float:
        if self.output_min is not None:
            value = max(self.output_min, value)
        if self.output_max is not None:
            value = min(self.output_max, value)
        return value

    def _clamp_integral(self, value: float) -> float:
        if self.integral_min is not None:
            value = max(self.integral_min, value)
        if self.integral_max is not None:
            value = min(self.integral_max, value)
        return value


def read_float(prompt: str) -> float:
    while True:
        try:
            return float(input(prompt))
        except ValueError:
            print("请输入数字，例如 0.25")


def main() -> None:
    pid = SwimPID(
        kp=0.6,
        ki=0.02,
        kd=0.08,
        feedforward=1.0,
        output_min=-2.0,
        output_max=2.0,
        integral_min=-1.0,
        integral_max=1.0,
    )

    print("Swim PID test. Press Ctrl+C to stop.")
    print("输入单位建议统一为 m/s。center_offset_speed 最好是带方向的速度。")

    try:
        while True:
            robot_speed = read_float("机器人自身速度 robot_speed: ")
            center_offset_speed = read_float("目标偏离中心点速度 center_offset_speed: ")
            expected_speed = pid.update(robot_speed, center_offset_speed)
            print(f"期望机器人速度 expected_robot_speed: {expected_speed:+.3f} m/s")
    except KeyboardInterrupt:
        print("\nPID stopped.")


if __name__ == "__main__":
    main()
