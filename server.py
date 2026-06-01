import ctypes
import json
import socket
import subprocess
import sys
import threading
from ctypes import wintypes
from pathlib import Path


CONFIG_PATH = Path(__file__).with_name("config.json")

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    )


class INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT))


class INPUT(ctypes.Structure):
    _fields_ = (("type", wintypes.DWORD), ("union", INPUTUNION))


user32 = ctypes.WinDLL("user32", use_last_error=True) if sys.platform == "win32" else None


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def send_input(input_event):
    sent = user32.SendInput(1, ctypes.byref(input_event), ctypes.sizeof(INPUT))
    if sent != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def set_cursor_position(message, config):
    width = max(int(config["capture_width"]), 1)
    height = max(int(config["capture_height"]), 1)
    x = int(config["capture_offset_x"] + float(message["x"]) * width)
    y = int(config["capture_offset_y"] + float(message["y"]) * height)
    user32.SetCursorPos(x, y)


def send_mouse(flags, mouse_data=0):
    event = INPUT(
        type=INPUT_MOUSE,
        union=INPUTUNION(mi=MOUSEINPUT(0, 0, mouse_data & 0xFFFFFFFF, flags, 0, None)),
    )
    send_input(event)


def send_key(virtual_key_code, is_down):
    flags = 0 if is_down else KEYEVENTF_KEYUP
    event = INPUT(
        type=INPUT_KEYBOARD,
        union=INPUTUNION(ki=KEYBDINPUT(virtual_key_code, 0, flags, 0, None)),
    )
    send_input(event)


def inject_input(message, config):
    kind = message.get("kind")
    if kind == "mouse-move":
        set_cursor_position(message, config)
    elif kind == "mouse-button":
        flags = {
            ("left", "down"): MOUSEEVENTF_LEFTDOWN,
            ("left", "up"): MOUSEEVENTF_LEFTUP,
            ("right", "down"): MOUSEEVENTF_RIGHTDOWN,
            ("right", "up"): MOUSEEVENTF_RIGHTUP,
            ("middle", "down"): MOUSEEVENTF_MIDDLEDOWN,
            ("middle", "up"): MOUSEEVENTF_MIDDLEUP,
        }.get((message.get("button"), message.get("action")))
        if flags:
            send_mouse(flags)
    elif kind == "mouse-wheel":
        send_mouse(MOUSEEVENTF_WHEEL, int(message.get("delta", 0)))
    elif kind == "key":
        virtual_key_code = int(message.get("virtualKeyCode", 0))
        if virtual_key_code:
            send_key(virtual_key_code, bool(message.get("isDown")))


def handle_input_client(conn, addr, config):
    print(f"input connected: {addr[0]}:{addr[1]}", flush=True)
    with conn, conn.makefile("r", encoding="utf-8", newline="\n") as lines:
        for line in lines:
            try:
                inject_input(json.loads(line), config)
            except Exception as exc:
                print(f"input error: {exc}", file=sys.stderr, flush=True)
    print(f"input disconnected: {addr[0]}:{addr[1]}", flush=True)


def run_input_server(config):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", int(config["input_port"])))
        listener.listen(1)
        print(f"input listening on 0.0.0.0:{config['input_port']}", flush=True)
        while True:
            conn, addr = listener.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            threading.Thread(
                target=handle_input_client,
                args=(conn, addr, config),
                daemon=True,
            ).start()


def build_ffmpeg_command(config):
    capture_size = f"{config['capture_width']}x{config['capture_height']}"
    output_url = f"tcp://0.0.0.0:{config['video_port']}?listen=1"
    return [
        config.get("ffmpeg_path", "ffmpeg"),
        "-hide_banner",
        "-loglevel",
        "info",
        "-f",
        "gdigrab",
        "-framerate",
        str(config["framerate"]),
        "-offset_x",
        str(config["capture_offset_x"]),
        "-offset_y",
        str(config["capture_offset_y"]),
        "-video_size",
        capture_size,
        "-draw_mouse",
        "1",
        "-i",
        "desktop",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-profile:v",
        "baseline",
        "-pix_fmt",
        "yuv420p",
        "-b:v",
        str(config["video_bitrate"]),
        "-maxrate",
        str(config["video_bitrate"]),
        "-bufsize",
        "500k",
        "-g",
        "15",
        "-keyint_min",
        "15",
        "-bf",
        "0",
        "-refs",
        "1",
        "-x264-params",
        "scenecut=0:sync-lookahead=0:rc-lookahead=0",
        "-fflags",
        "nobuffer",
        "-flush_packets",
        "1",
        "-f",
        "h264",
        output_url,
    ]

def main():
    if sys.platform != "win32":
        print("server.py must run on Windows for gdigrab and SendInput", file=sys.stderr)
        sys.exit(1)

    config = load_config()
    threading.Thread(target=run_input_server, args=(config,), daemon=True).start()

    command = build_ffmpeg_command(config)
    print(f"video listening on 0.0.0.0:{config['video_port']}", flush=True)
    print("starting ffmpeg capture", flush=True)
    try:
        subprocess.run(command, check=True)
    except KeyboardInterrupt:
        print("stopping", flush=True)
    except FileNotFoundError:
        print("ffmpeg was not found; install FFmpeg or edit config.json", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
