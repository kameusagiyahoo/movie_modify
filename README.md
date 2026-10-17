# Movie Modify — privacy-first modular video editor

A **working local MVP** for standard smartphone MP4/MOV and **already-stitched equirectangular 360° video**. Separate import adapters, analysis plug-ins, edit decisions and FFmpeg renderer keep the system extensible. Videos are not uploaded to a cloud service.

## What works

- Import local MP4/MOV/MKV/WebM (up to 50 GiB per upload) and generate a small H.264 browser preview in the background.
- Select regular (flat) video or **equirectangular 360°** at import time.
- Generate **non-destructive cut suggestions** using FFmpeg `silencedetect`, with optional [Auto-Editor](https://auto-editor.com/) v1 timeline support.
- Manually approve suggestions. Split segments at the player position; keep / cut individual segments.
- For 360° sources, change **yaw / pitch / FOV per segment**, view a still preview from the original footage. Each segment can show the child *or* the scenery.
- Render the kept intervals to 720p or 1080p 16:9 MP4 with original audio, using FFmpeg; watch job progress and download the output.
- Phone-friendly local Web UI; projects and original media stay on disk in `data/` (gitignored).

## Quick start (Ubuntu / Linux)

Install Python 3.10+ and FFmpeg:

```bash
sudo apt update && sudo apt install -y ffmpeg python3-venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn movie_modify.server:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** on this machine. Select a video to import. No external API keys are required.

For optional Auto-Editor suggestions:

```bash
pip install -r requirements-optional.txt
```

Auto-Editor can consume more CPU than audio-only silence detection. Versioned v1 export is used instead of parsing its console output.

### Access from iPhone on your private Wi-Fi

**Do not expose this service to the public Internet.** On a trusted home LAN, configure an access token and bind to the local network:

```bash
export MOVIE_MODIFY_TOKEN='choose-a-long-random-passphrase'
python -m uvicorn movie_modify.server:app --host 0.0.0.0 --port 8000
```

Find your PC's LAN IP (`hostname -I`) and visit `http://PC_LAN_IP:8000` on iPhone. The app will ask for the passphrase, and use an HttpOnly cookie. **HTTP on Wi-Fi is not encrypted.** For sensitive family video, prefer local access or add HTTPS via a trusted reverse proxy (or use a private VPN); never forward port 8000 to the Internet.

## Processing stages / plug-in boundaries

| Layer | Module | Depends on camera? | Requirement |
|---|---|---|---|
| Media import / probe | `server.py` + `media.inspect_video` | input format only | FFprobe |
| Normalization / proxy | `media.create_proxy` | projection flag | FFmpeg |
| Candidate cut detection | `media.silence_suggestions` | no | FFmpeg |
| Alternative cut detection | `media.auto_editor_suggestions` | no | optional Auto-Editor |
| Edit decision list / intervals | `core.py` | no | Python stdlib |
| Viewpoint projection | `media.view_filter` | **360° only** | FFmpeg `v360` |
| Render / concatenate | `media.render` | projection flag | FFmpeg |
| Review UI | `web/index.html` | uses capability flags | Modern browser |

JSON `segments` use *source* seconds, are ordered and non-overlapping. Each has `start`, `end`, `keep`, `yaw`, `pitch`, `fov`. Nothing deletes the original media. Auto-Editor analysis never applies cuts without the user's approval. Scenes, VLM, speech transcription and tracking can be installed as **future analysis plug-ins** that emit the same timecoded suggestions or view keyframes.

### 360 camera limitations

Vendor-specific files (`.insv`, `.360`, dual-fisheye) need the camera manufacturer's **stitching / horizon-stabilization tool** to output equirectangular MP4/MOV first. A 2:1 aspect ratio alone does *not* prove that a source is stitched, and this app does not infer it automatically. Currently viewport orientation is **static within each segment**; a dynamic person-tracking / keyframe interpolation adapter is planned, not represented as complete. Flat smartphone videos support cuts but not an invented off-frame camera view.

### Known MVP constraints

- Cut suggestions based on silence can wrongly flag quiet but meaningful family moments; approval is required.
- Rendering re-encodes each kept segment to consistent H.264/AAC, which is CPU-intensive for long or 8K footage; processing is serialized to protect machines with limited memory.
- Browser preview is a fixed front-facing viewport for 360°; the still-image viewpoint preview and final output use segment settings.
- The app edits **one source video per project**; multi-camera/multi-clip timelines are future extensions.
- Networked UI has no HTTPS by itself; LAN token protects endpoints but does not encrypt traffic.
- The job queue and progress are in memory; projects, cuts and exports remain on disk after restart. Large uploads are written in chunks; close the app carefully during processing.

## Tests

```bash
pip install pytest
pytest -q
```

## Roadmap

1. Add scene/motion detection as analysis plug-ins (PySceneDetect, models), without touching EDL.
2. 360 moving **yaw/pitch keyframes** and local person tracking; use camera-native tracking metadata where available.
3. Multi-source timeline and automatic event grouping.
4. Media indexing, encrypted backups and resumable render queues.
