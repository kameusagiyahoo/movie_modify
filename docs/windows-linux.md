# Movie Modify local server: Windows and Linux

Both systems run **the same Python backend** and the same responsive HTML/JS
interface. Video/audio never need to leave your machine. GitHub Pages remains
an independent browser-only alternative that cannot execute native FFmpeg and
OpenCV.

## Requirements

- Windows 10/11 (64-bit) or a current Linux distribution. Automated CI
  runs on GitHub's windows-latest and ubuntu-latest runners; consumer PC hardware
  and iPhone Safari need separate real-device confirmation. Python 3.11+ is recommended.
- FFmpeg **and FFprobe** on PATH; the FFmpeg build must include libx264, AAC,
  v360 and sendcmd. 360 camera-native .insv/.360 files still need manufacturer
  stitching before import.
- The optional appearance tracker needs the packages in
  requirements-tracking.txt (OpenCV and NumPy).
- RAM: 16 GB recommended for normal use, 32 GB or more for larger projects.
  Disk space must cover source videos, proxies and export files.

## Windows PowerShell

Install Python from python.org or Windows package manager.
Install FFmpeg (then **reopen the terminal** so the PATH is refreshed):

    winget install --id Gyan.FFmpeg -e

Check:

    py -3 --version
    ffmpeg -version
    ffprobe -version

From the repository root:

    .\scripts\start-windows.cmd

The first run creates .venv and installs core dependencies. Open
http://127.0.0.1:8000 on the computer. For optional tracking:

    .\.venv\Scripts\python.exe -m pip install -r requirements-tracking.txt

For optional Auto-Editor:

    .\.venv\Scripts\python.exe -m pip install -r requirements-optional.txt

## Linux (Ubuntu)

    sudo apt update
    sudo apt install -y python3-venv ffmpeg
    bash scripts/start-linux.sh

The first run creates .venv and installs dependencies. Open
http://127.0.0.1:8000 in a browser. Optional tracking:

    .venv/bin/python -m pip install -r requirements-tracking.txt

Optional Auto-Editor:

    .venv/bin/python -m pip install -r requirements-optional.txt

## Shared CLI on either OS

The server starts **loopback-only by default**, so no other device can reach it:

    python -m movie_modify
    python -m movie_modify --port 8080
    python -m movie_modify --data-dir "D:\Family Videos\Movie Modify"

Use the .venv Python path or start script when dependencies are installed only
in the virtual environment. The data directory can be on an external SSD.
Paths with spaces, apostrophes and Windows drive letters are supported.

### Connect from iPhone on the same private network

Set a long random MOVIE_MODIFY_TOKEN **before** starting the server, then pass
--lan. This is not intended for public hosting.

PowerShell:

    $env:MOVIE_MODIFY_TOKEN = "replace-with-a-unique-long-secret"
    .\scripts\start-windows.cmd --lan

Windows Command Prompt:

    set MOVIE_MODIFY_TOKEN=replace-with-a-unique-long-secret
    scripts\start-windows.cmd --lan

Linux:

    export MOVIE_MODIFY_TOKEN="replace-with-a-unique-long-secret"
    bash scripts/start-linux.sh --lan

Find your PC's LAN IP using ipconfig (Windows) or hostname -I (Linux).
Open http://PC_LAN_IP:8000 in iPhone Safari.

On Windows, allow the Python server through the firewall on the **Private**
network only if required. Do **not** forward port 8000 to the Internet.
The application passphrase is not HTTPS: unencrypted HTTP Wi-Fi traffic is
not confidential. Use an HTTPS reverse proxy or private VPN for security.

Note: Projects live on the host PC; connecting from iPhone operates that
computer's storage and encoding engine. The GitHub Pages editor stores its
browser-local edit data independently; syncing its edits with the local server
has not been implemented yet.

## Troubleshooting

- **FFmpeg/FFprobe not found:** install both and reopen the terminal.
- **Python venv unavailable:** install Python 3.11+ and ensure it is on PATH.
- **Tracking not available:** install requirements-tracking.txt inside .venv.
- **iPhone cannot connect:** check both devices on same network, server started
  with --lan and MOVIE_MODIFY_TOKEN, and Windows Private firewall.
- **Large 8K renders are slow:** normal on CPU; use a shorter test video first.
- **Not all codec variants play in Safari:** the server generates H.264 browser
  proxies. Camera vendor-specific videos require a compatible conversion.
