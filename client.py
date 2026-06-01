import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from pynput import keyboard, mouse


CONFIG_PATH = Path(__file__).with_name("config.json")

SPECIAL_KEYS = {
    keyboard.Key.backspace: 0x08,
    keyboard.Key.tab: 0x09,
    keyboard.Key.enter: 0x0D,
    keyboard.Key.shift: 0x10,
    keyboard.Key.shift_l: 0x10,
    keyboard.Key.shift_r: 0x10,
    keyboard.Key.ctrl: 0x11,
    keyboard.Key.ctrl_l: 0x11,
    keyboard.Key.ctrl_r: 0x11,
    keyboard.Key.alt: 0x12,
    keyboard.Key.alt_l: 0x12,
    keyboard.Key.alt_r: 0x12,
    keyboard.Key.pause: 0x13,
    keyboard.Key.caps_lock: 0x14,
    keyboard.Key.esc: 0x1B,
    keyboard.Key.space: 0x20,
    keyboard.Key.page_up: 0x21,
    keyboard.Key.page_down: 0x22,
    keyboard.Key.end: 0x23,
    keyboard.Key.home: 0x24,
    keyboard.Key.left: 0x25,
    keyboard.Key.up: 0x26,
    keyboard.Key.right: 0x27,
    keyboard.Key.down: 0x28,
    keyboard.Key.insert: 0x2D,
    keyboard.Key.delete: 0x2E,
    keyboard.Key.f1: 0x70,
    keyboard.Key.f2: 0x71,
    keyboard.Key.f3: 0x72,
    keyboard.Key.f4: 0x73,
    keyboard.Key.f5: 0x74,
    keyboard.Key.f6: 0x75,
    keyboard.Key.f7: 0x76,
    keyboard.Key.f8: 0x77,
    keyboard.Key.f9: 0x78,
    keyboard.Key.f10: 0x79,
    keyboard.Key.f11: 0x7A,
    keyboard.Key.f12: 0x7B,
}

CHAR_KEYS = {
    "\b": 0x08,
    "\t": 0x09,
    "\r": 0x0D,
    "\n": 0x0D,
    " ": 0x20,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    ";": 0xBA,
    "'": 0xDE,
    "[": 0xDB,
    "]": 0xDD,
    "\\": 0xDC,
    "-": 0xBD,
    "=": 0xBB,
    "`": 0xC0,
}


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_screen_size():
    try:
        import tkinter

        root = tkinter.Tk()
        root.withdraw()
        size = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return size
    except Exception:
        return 1, 1


def virtual_key_code(key):
    vk = getattr(key, "vk", None)
    if vk:
        return int(vk)
    if key in SPECIAL_KEYS:
        return SPECIAL_KEYS[key]
    char = getattr(key, "char", None)
    if not char:
        return 0
    if char.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        return ord(char.upper())
    if char in "0123456789":
        return ord(char)
    return CHAR_KEYS.get(char, 0)


class InputForwarder:
    def __init__(self, config):
        self.config = config
        self.sock = None
        self.lock = threading.Lock()
        self.screen_width, self.screen_height = get_screen_size()

    def connect(self):
        while True:
            try:
                sock = socket.create_connection(
                    (self.config["server_ip"], int(self.config["input_port"])),
                    timeout=3,
                )
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sock = sock
                print("input connected", flush=True)
                return
            except OSError as exc:
                print(f"waiting for input socket: {exc}", flush=True)
                time.sleep(1)

    def send(self, message):
        payload = (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
        with self.lock:
            try:
                self.sock.sendall(payload)
            except OSError:
                self.connect()
                self.sock.sendall(payload)

    def on_move(self, x, y):
        self.send(
            {
                "kind": "mouse-move",
                "x": max(0.0, min(1.0, x / self.screen_width)),
                "y": max(0.0, min(1.0, y / self.screen_height)),
            }
        )

    def on_click(self, x, y, button, pressed):
        self.on_move(x, y)
        self.send(
            {
                "kind": "mouse-button",
                "button": str(button).split(".")[-1],
                "action": "down" if pressed else "up",
            }
        )

    def on_scroll(self, x, y, dx, dy):
        self.on_move(x, y)
        self.send({"kind": "mouse-wheel", "delta": int(dy * 120)})

    def on_key(self, key, is_down):
        vk = virtual_key_code(key)
        if vk:
            self.send({"kind": "key", "virtualKeyCode": vk, "isDown": is_down})

    def run(self):
        self.connect()
        mouse_listener = mouse.Listener(
            on_move=self.on_move,
            on_click=self.on_click,
            on_scroll=self.on_scroll,
        )
        keyboard_listener = keyboard.Listener(
            on_press=lambda key: self.on_key(key, True),
            on_release=lambda key: self.on_key(key, False),
        )
        mouse_listener.start()
        keyboard_listener.start()
        mouse_listener.join()
        keyboard_listener.join()


def build_ffplay_command(config):
    input_url = f"tcp://{config['server_ip']}:{config['video_port']}"
    return [
        config.get("ffplay_path", "ffplay"),
        "-hide_banner",
        "-loglevel",
        "warning",
        "-fflags",
        "nobuffer",
        "-flags",
        "low_delay",
        "-framedrop",
        "-probesize",
        "1024",
        "-analyzeduration",
        "0",
        "-sync",
        "ext",
        "-f",
        "h264",
        "-window_title",
        "P2PC Stream",
        input_url,
    ]


def main():
    config = load_config()
    forwarder = InputForwarder(config)
    threading.Thread(target=forwarder.run, daemon=True).start()

    command = build_ffplay_command(config)
    print(f"connecting video to {config['server_ip']}:{config['video_port']}", flush=True)
    try:
        subprocess.run(command, check=True)
    except KeyboardInterrupt:
        print("stopping", flush=True)
    except FileNotFoundError:
        print("ffplay was not found; install FFmpeg or edit config.json", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        sys.exit(exc.returncode)


if __name__ == "__main__":
    main()
