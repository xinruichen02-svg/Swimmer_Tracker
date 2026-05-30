import cv2
import time
import math
from collections import deque


def create_tracker():
    if hasattr(cv2, "legacy") and hasattr(cv2.legacy, "TrackerCSRT_create"):
        return cv2.legacy.TrackerCSRT_create()
    if hasattr(cv2, "TrackerCSRT_create"):
        return cv2.TrackerCSRT_create()
    


def bbox_center(bbox):
    x, y, w, h = bbox
    cx = x + w / 2.0
    cy = y + h / 2.0
    return cx, cy


def main():
    VIDEO_SOURCE = 0

    # 标定参数：每多少像素对应 1 米
    
    PIXELS_PER_METER = 120.0

    # 测速方向：
    MEASURE_AXIS = "xy"

    SMOOTH_WINDOW = 5

    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print("无法打开视频源")
        return

    ret, frame = cap.read()
    if not ret:
        print("无法读取首帧")
        return

    print("请框选游泳运动员")
    bbox = cv2.selectROI("Select Target", frame, fromCenter=False, showCrosshair=True)
    cv2.destroyWindow("Select Target")

    if bbox == (0, 0, 0, 0):
        print("没有选中目标")
        return

    tracker = create_tracker()
    tracker.init(frame, bbox)

    prev_cx, prev_cy = bbox_center(bbox)
    prev_time = time.time()

    speed_buffer = deque(maxlen=SMOOTH_WINDOW)

    center_x = None
    center_y = None
    prev_dx_center = 0.0
    prev_dy_center = 0.0
    center_speed_buffer = deque(maxlen=SMOOTH_WINDOW)

    while True:
        ret, frame = cap.read()
        frame=cv2.GaussianBlur(frame,(5,5),0)
        
        if not ret:
            break

        if center_x is None:
            center_x = frame.shape[1] // 2
            center_y = frame.shape[0] // 2

        # 画十字线
        cv2.line(frame, (0, center_y), (frame.shape[1], center_y), (255, 255, 255), 1)
        cv2.line(frame, (center_x, 0), (center_x, frame.shape[0]), (255, 255, 255), 1)

        now = time.time()
        dt = max(now - prev_time, 1e-6)

        ok, bbox = tracker.update(frame)

        if ok:
            x, y, w, h = [int(v) for v in bbox]
            cx, cy = bbox_center((x, y, w, h))

            dx = cx - prev_cx
            dy = cy - prev_cy

            if MEASURE_AXIS == "x":
                pixel_disp = dx
            elif MEASURE_AXIS == "y":
                pixel_disp = dy
            else:
                pixel_disp = math.hypot(dx, dy)

            speed_px_s = pixel_disp / dt
            speed_m_s = (pixel_disp / PIXELS_PER_METER) / dt

            speed_buffer.append(speed_m_s)
            smooth_speed = sum(speed_buffer) / len(speed_buffer)

            # 计算相对中心的位移
            dx_center = cx - center_x
            dy_center = cy - center_y

            # 计算相对中心的速度
            ddx_center = dx_center - prev_dx_center
            ddy_center = dy_center - prev_dy_center
            speed_center_px_s = math.hypot(ddx_center, ddy_center) / dt
            speed_center_m_s = (math.hypot(ddx_center, ddy_center) / PIXELS_PER_METER) / dt

            center_speed_buffer.append(speed_center_m_s)
            smooth_center_speed = sum(center_speed_buffer) / len(center_speed_buffer)

            cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(frame, (int(cx), int(cy)), 4, (0, 0, 255), -1)

            cv2.putText(frame, f"dx: {dx:+.2f}px  dy: {dy:+.2f}px", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            cv2.putText(frame, f"Speed: {speed_px_s:+.2f} px/s", (20, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            cv2.putText(frame, f"Speed: {smooth_speed:+.2f} m/s", (20, 110),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            cv2.putText(frame, f"Center dx: {dx_center:+.2f}px  dy: {dy_center:+.2f}px", (20, 145),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            cv2.putText(frame, f"Center Speed: {smooth_center_speed:+.2f} m/s", (20, 180),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

            prev_cx, prev_cy = cx, cy
            prev_dx_center = dx_center
            prev_dy_center = dy_center
            prev_time = now

        else:
            cv2.putText(frame, "Tracking lost", (20, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            prev_time = now

        cv2.imshow("Swimmer Speed Measurement", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == 27 or key == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()