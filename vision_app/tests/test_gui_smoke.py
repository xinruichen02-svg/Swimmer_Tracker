import unittest

from vision_app.swimming_app import SwimControlApp


class GuiSmokeTests(unittest.TestCase):
    def test_virtual_backend_is_explicit_and_connects_through_supervisor(self):
        app = SwimControlApp()
        try:
            app.backend_var.set("virtual")
            app._on_backend_selected()
            app.connect_serial()
            app.root.update_idletasks()
            self.assertTrue(app.motor.connected)
            self.assertIn("仿真模式", app.backend_badge_var.get())
            self.assertFalse(app.motor.is_real)
        finally:
            app._closing = True
            app.motor.disconnect(send_stop=True)
            app.vision.release()
            app.root.destroy()


if __name__ == "__main__":
    unittest.main()
