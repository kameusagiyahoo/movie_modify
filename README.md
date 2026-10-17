# Movie Modify — privacy-first modular video editor

A **working local MVP** for standard smartphone MP4/MOV and **already-stitched equirectangular 360° video**. Separate import adapters, analysis plug-ins, edit decisions and FFmpeg renderer keep the system extensible. Videos are not uploaded to a cloud service.

## What works

- Import local MP4/MOV/MKV/WebM (up to 50 GiB per upload) and generate a small H.264 browser preview in the background.
- Select regular (flat) video or **equirectangular 360°** at import time.
- Generate **non-destructive cut suggestions** using FFmpeg `silencedetect`, with optional [Auto-Editor](https://auto-editor.com/) v1 timeline support.
- Manually approve suggestions. Split segments at the player position; keep / cut individual segments.
- For stitched 360° sources, select a person in a panoramic still and generate local OpenCV **auto-follow keyframes**. Switch to a fixed or manually keyframed scenic view at any point in the **same timeline**. The trajectory is rendered into 16:9 MP4.
- Manually edit yaw/pitch/FOV at several times; angles smoothly interpolate by the shortest direction across the 360° seam. Camera keyframes remain valid after splitting or applying cut suggestions.
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

For optional 360° person/appearance tracking (processed locally; no downloaded neural-network weights):

```bash
pip install -r requirements-tracking.txt
```

Use a stitched 2:1 panorama, place the playhead, split the timeline where the desired camera mode changes, select **人物追尾**, tap a person in the panorama, and run **選択した人物を自動追尾**. For scenery, select **ここから景色に切り替え**, tap the desired panorama direction, and add further keyframes to create a smooth pan. Then save and render as usual.

This is an **appearance tracker, not verified child identification**: other people, camera shake, changing lighting, seam crossings or temporary occlusion can cause tracking drift. Check the resulting camera trajectory before export. Each tracking job is limited to 20 minutes; longer footage is split into segments first. The fixed-front browser video preview does not show the moving output directly: use **選択画角の静止画を見る** at chosen times, or render the output.

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

JSON `segments` use *source* seconds, are ordered and non-overlapping. Each has `start`, `end`, `keep`, `yaw`, `pitch`, `fov`, `mode` (`manual` or `follow`), and optional source-time `keyframes` (`time`, `yaw`, `pitch`, `fov`). Nothing deletes the original media. Auto-Editor analysis never applies cuts without the user's approval. Additional scene classifiers, VLMs and speech transcription can be installed as **future analysis plug-ins** that emit timecoded suggestions or camera keyframes.

### 360 camera limitations

Vendor-specific files (`.insv`, `.360`, dual-fisheye) need the camera manufacturer's **stitching / horizon-stabilization tool** to output equirectangular MP4/MOV first. A 2:1 aspect ratio alone does *not* prove that a source is stitched, and this app does not infer it automatically. The optional OpenCV adapter generates moving keyframes for locally selected targets. It is not an identity-recognition model and cannot guarantee correct tracking through occlusions. Flat smartphone videos support cuts but not an invented off-frame camera view.

### Known MVP constraints

- Cut suggestions based on silence can wrongly flag quiet but meaningful family moments; approval is required.
- Rendering re-encodes each kept segment to consistent H.264/AAC, which is CPU-intensive for long or 8K footage; processing is serialized to protect machines with limited memory.
- Browser video preview is fixed front-facing for 360°; the still-image viewpoint preview samples the active keyframe trajectory, and final output uses animated orientation.
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
2. Improve tracker resilience (camera motion / occlusion / seam tests); optionally import camera-native tracking metadata.
3. Multi-source timeline and automatic event grouping.
4. Media indexing, encrypted backups and resumable render queues.


## yomiyasu: Japanese writing for development

The [yomiyasu](https://github.com/nanaism/yomiyasu) Agent Skill is vendored
at [`.agents/skills/yomiyasu/`](.agents/skills/yomiyasu/SKILL.md).
It helps Codex revise Japanese documentation, UI instructions and PR text.
Use `/yomiyasu` or `$yomiyasu:yomiyasu` from Codex. This is **not**
a video editor, subtitle engine, or AI inference component; it never runs
in the Movie Modify media backend. See [the guide](docs/yomiyasu.md).


## Continuous in-editor 360° preview

The editor can now **play the selected 16:9 direction continuously** while a
360° source video is playing. It uses a same-origin H.264 **2:1 panoramic
proxy** and a dependency-free WebGL renderer in the browser:

- Select a **stitched equirectangular 360° MP4/MOV**. Normal phone videos keep
  their existing native video player.
- For a 360° project, press **再生** above the timeline. The preview follows the
  existing person's generated keyframes and pans to manually selected scenic
  angles at the right times. Scrub with the playback slider to inspect changes.
- **カット区間を飛ばす** is enabled by default while playing. Uncheck it if you
  want to review all source frames including cut sections.
- Manual scenery keyframes and local OpenCV tracking remain independent and
  editable. The browser viewer reads exactly the current unsaved segment data;
  no new MP4 export is required just to review a different view angle.
- If WebGL is unavailable, the original 2:1 low-resolution proxy can still be
  played, and the existing single-frame preview remains available.

On initial import of a **new 360° project**, one background transcoding job
creates \`data/<id>/proxy360.mp4\` at 1280×640 and 24 fps. Older projects
without a panoramic proxy generate one on demand upon opening in the editor.
The backend reuses an in-progress import job instead of encoding twice. The
source remains untouched.

**Privacy:** No cloud API or external video hosting is used. The proxy video
is streamed between your own server and its browser client. For viewing over
a local Wi-Fi network, protect access with \`MOVIE_MODIFY_TOKEN\`; use HTTPS
if other people can inspect your LAN traffic.

**Limitations:** The preview's low-resolution WebGL projection approximates
the FFmpeg high-quality final render; minor differences are possible.
Browser decoding and WebGL performance vary, especially with older iPhones.
Source audio follows the selected time; there is no crossfade at cut points.
Trackers may drift when a person is obstructed, so inspect those intervals.


## Editing UI — iPhone and desktop with one shared project

The same locally hosted Web UI adapts to the screen, **without duplicating the
editing engine or storing separate phone/desktop timelines**:

| | iPhone / narrow browser (up to 900px) | Desktop / wide browser |
|---|---|---|
| Main view | Sticky video preview and large touch targets | Two-column workspace: preview + timeline, with review/export tools beside it |
| Editing tools | Tabs: タイムライン / 自動カット / 書き出す | Tools visible concurrently |
| Fast actions | Bottom bar: 分割 / 景色 (or 自動カット for flat footage) / 残す・カット / 保存 | Editing toolbar and keyboard shortcuts |
| Timeline | Pinch with two fingers or press +/- to zoom; swipe horizontally | +/- zoom, horizontal mouse/trackpad scrolling, click-to-seek |
| Asset library | Open the 素材・履歴 drawer | Always visible left sidebar |

**Keyboard shortcuts on desktop** (when not typing in a form field):
Space to play/pause, \`S\` to split at the playhead, and left/right arrow to
seek 5 seconds. Edits are still saved with the **保存** action (not silently
autosaved). Existing person-follow and scenery keyframes use the same source
timeline from either device.

**Important:** Both clients connect to the *same local video project stored on
your PC*. Moving from PC to iPhone is supported over the same network, but
simultaneous editing in multiple browser tabs is not yet conflict-safe. Finish
and save on one device before modifying the project on the other. Browser
screen size controls the layout; you do not need to select a permanent mode.

The responsive UI is split into \`web/responsive_ui.css\` and
\`web/responsive_ui.js\`. These are served locally at \`/assets/\` (no external
UI CDN), while \`movie_modify/core.py\` and the render pipeline remain
unchanged. In particular, the ordinary smartphone-video workflow is preserved.

## GitHub Pages（ブラウザで動く編集アプリ）

`docs/` に静的な動画編集アプリを追加しました。iPhone・PCで通常動画の分割やカット指定、変換済み360度MP4の画角キーフレーム編集・連続プレビュー、編集JSONの保存・読込ができます。選んだ動画ファイルをサーバーへ送信せず、ブラウザ内で処理します。

**公開設定:** GitHubの **Settings → Pages → Deploy from a branch → main /docs → Save** を選んでください。すでに `main /(root)` を指定している場合はトップページから `docs/` へ移動します。

**制限:** PagesではPython・Auto-Editor・OpenCV・FFmpegを実行できません。新しい人物の自動追尾、自動カット解析、安定した高品質書き出しにはローカル版を利用します。MediaRecorder対応ブラウザに限り等倍速での試験的書き出しを利用できますが、音声・形式・性能はブラウザ依存です。プライベートな動画を公開GitHubリポジトリに置かないでください。

[アプリ](docs/index.html)／[説明・公開手順](docs/README.md)
