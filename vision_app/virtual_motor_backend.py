from __future__ import annotations

import uuid

from vision_app.python_can_backend import PythonCanBackend
from vision_app.simulated_motor import SimulatedMotor


class VirtualMotorBackend(PythonCanBackend):
    name = "virtual"
    is_real = False

    def __init__(self, *, channel: str | None = None) -> None:
        virtual_channel = channel or f"swimmer-{uuid.uuid4().hex}"
        super().__init__(interface="virtual", channel=virtual_channel)
        self._simulator = SimulatedMotor(virtual_channel)

    @property
    def simulator(self) -> SimulatedMotor:
        return self._simulator

    def connect(self) -> None:
        self._simulator.start()
        try:
            super().connect()
        except Exception:
            self._simulator.close()
            raise

    def close(self) -> None:
        super().close()
        self._simulator.close()

