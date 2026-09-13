import socket
import threading

# ============ 按需修改 ============
HOST = "192.168.1.177"   # Arduino的静态IP
PORT = 8888              # 和代码里的端口一致
# =================================

s = socket.create_connection((HOST, PORT), timeout=5)
print(f"已连接 {HOST}:{PORT}")
print("输入命令: S(启动) / P(停止) / T600(设转速) / quit(退出)\n")


def reader():
    """后台线程：持续打印Arduino发回的反馈"""
    while True:
        try:
            data = s.recv(4096)
            if not data:
                print("\n[连接已关闭]")
                break
            print(data.decode(errors="ignore"), end="", flush=True)
        except Exception:
            break


t = threading.Thread(target=reader, daemon=True)
t.start()

try:
    while True:
        cmd = input("> ")
        if cmd.strip().lower() == "quit":
            break
        s.sendall((cmd.strip() + "\n").encode())
except (EOFError, KeyboardInterrupt):
    pass

s.close()
