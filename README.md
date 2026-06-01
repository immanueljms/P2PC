# P2PC FFmpeg TCP Prototype

Tiny proof-of-concept peer-to-peer game streaming tools:

- Windows host captures the desktop with FFmpeg `gdigrab`, encodes H.264 with `libx264`, and serves raw H.264 over TCP.
- Viewer connects with `ffplay`, displays the stream, captures local keyboard/mouse input with `pynput`, and forwards JSON events over a second TCP socket.
- Host injects input with the Windows `SendInput` API via Python `ctypes`.

No auth, no UI, no NAT traversal, no encryption. Run only on a trusted LAN.

## Setup

Install FFmpeg on both machines and make sure `ffmpeg` and `ffplay` are on `PATH`.

Install the client dependency:

```powershell
python -m pip install -r poc_stream\requirements.txt
```

On non-Windows clients, use the equivalent shell command.

## Configure

Edit `poc_stream/config.json`.

- `server_ip`: host machine IP as seen from the client.
- `video_port`: TCP port for raw H.264 video.
- `input_port`: TCP port for keyboard/mouse events.
- `capture_width` / `capture_height`: area captured from the Windows desktop.
- `capture_offset_x` / `capture_offset_y`: top-left capture offset.
- `video_bitrate`: start with `6M`, raise for quality, lower for weak networks.

Open both ports in Windows Firewall if needed.

## Run

On the Windows host:

```powershell
python poc_stream\server.py
```

On the viewer:

```powershell
python poc_stream\client.py
```

## Latency Notes

The command line favors latency over quality:

- `-preset ultrafast`
- `-tune zerolatency`
- no B-frames
- short GOP
- raw H.264 over TCP
- `ffplay` with `nobuffer`, tiny probe size, and frame dropping

TCP can still add latency when packets are lost. For a real system, RTP/UDP or WebRTC is usually a better transport, but TCP keeps this proof of concept intentionally small.
