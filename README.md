# Movie Modify — privacy-first modular video editor

> **[統合仕様書（最新版・日本語・構成図付き）](docs/SPECIFICATION.md)** — 機能要件、画面設計、システム構成、編集JSON、API、プラットフォーム、検証状況、ロードマップの**正本**。このREADMEは概要と起動案内です。

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

## R-05: cautious subject re-acquisition for 360° tracking

The offline OpenCV tracker now validates CSRT positions against the
**unchanged first-frame appearance** selected by the user. When the selected
person is occluded or the match is unreliable, it **holds the last trusted
camera orientation** rather than drifting to a visually similar person.
Re-acquisition searches a widening *local* region of the stitched panorama,
including the 360° seam, and requires stronger evidence after a long gap.
Ambiguous competing matches are rejected, and the project records a warning
with lost-frame duration and recovery counts.

This is not facial recognition or an identity guarantee: long occlusions,
outfit changes, camera motion, and similar people can still cause a lost track.
Review the generated follow segment and use manual scenery/keyframes when
necessary. The change is tested against synthetic occlusion clips; **real
family footage and iPhone preview performance remain to be verified**.

See [the integrated specification](docs/SPECIFICATION.md#84-360度人物追尾).

## R-10 (partial): PC-side edit revision backups

Every committed EDL change archives the **previous** source-timeline edits in
`data/<project-id>/edit_history/<revision>.json.gz` on the local PC.
Up to **30 older revisions** are retained, independently of browser tabs,
the last autosave draft and the original movie. The advanced editor and Studio
can open the **PC保存履歴** list and restore an earlier revision. Restoration
archives the current edits first and creates a new revision, guarded against
stale writes with `expected_revision`.

No media bytes are duplicated by this EDL history. These are backups on the
**same disk**, so they do not survive drive failure or manual removal of the
data directory. FFmpeg render jobs do not yet survive server restarts.

## R-03 / R-04: safe multi-device edits and resumable local transfer

The Windows/Linux backend now stores an integer **edit_revision** with each
project. Studio and the advanced editor must supply the last-read revision
when saving edits or applying automated cut results. Stale updates are
rejected with **HTTP 409 Conflict**, preserving the newer saved work.
Automatic tracking jobs also verify the revision before applying their
output. This prevents blind last-writer-wins overwrites when another browser
or device edits the same project. It does not automatically merge edits.

When transferring source video from the local Studio (including an iPhone
connecting to your PC), the media is sent in **4 MiB chunks** with a progress
bar and **Pause** action. Upload status is retained on PC disk: after
reselecting the same source file, a transfer interrupted by Wi-Fi disconnection
or browser refresh can resume from the verified byte offset. Idempotent
retries do not append duplicate bytes. Server chunks are limited to 8 MiB,
with a 50 GiB file cap; unused upload sessions expire after 24 hours.
The source is transferred **only to the local PC**, and only after confirmation.

**Important limits:** No automatic Pages→PC background connection, no conflict
auto-merge, and no end-to-end encryption on local HTTP. iPhone Safari and
very large real-world transfers still require hardware testing. A backend
FFmpeg job itself does not resume after server restart; only the incoming
upload bytes are persisted.

See [the canonical specification](docs/SPECIFICATION.md) for the protocol
and accepted limitations.

## R-02: automatic edit draft protection (Pages / Studio / advanced editor)

Both the static Pages editor and Windows/Linux local web editor now support:

- **Undo/Redo** for timeline cuts, splitting and view-angle/keyframe changes,
  including browser-history selection of recent actions. Native tracking and
  automatic-cut results are also recorded in the advanced editor.
- **Browser-local automatic draft save** after each meaningful edit. The saved
  draft contains the edit decision list and playhead/selection only; never
  source movie bytes.
- **Explicit restoration on reopen**. Pages requires the original video to be
  selected again and checks its name, size, modification time, duration,
  projection and resolution. The advanced editor also checks the saved
  project's baseline and refuses to auto-apply outdated drafts.
- **Protection against storage errors**. Users can still download a JSON copy.
  The advanced editor offers JSON recovery for drafts that conflict with the
  PC's current project state.

History contains up to 40 snapshots in tab memory (the latest draft alone is
persisted to `localStorage`). Browsers can clear local drafts; save a manual
JSON backup for important work. **Local auto-save is not PC server auto-sync**:
continue using the editor's Save / Studio Sync command when you want to persist
edits on your Windows/Linux machine or move between devices. Stale-server-write protection is implemented in R-03; full automatic
conflict merging is still future work.

See the [canonical specification, section 7.5](docs/SPECIFICATION.md#75-編集履歴自動保存復元r-02).

## GitHub Pages → local PC handoff (Windows / Linux)

The same browser editor can now be opened from the local processing server:

- **Static Pages editor:** https://kameusagiyahoo.github.io/movie_modify/
- **Local connected studio:** http://127.0.0.1:8000/studio/
- **Advanced local editor:** http://127.0.0.1:8000/

After running the Windows or Linux launcher, choose **PCの高機能エンジン**
in the Pages editor. Save your edit JSON, navigate to the local studio
(on iPhone, replace 127.0.0.1 with your PC's private LAN IP), then reselect
the source movie and edit JSON. In the local studio, an explicit confirmation
allows the user to **upload the selected video to their own PC** once and
synchronize the EDL, render with FFmpeg, or open the advanced UI for OpenCV
tracking and automatic cut suggestions.

This uses **navigation rather than cross-origin fetch**: GitHub Pages HTTPS
cannot reliably call private-network HTTP APIs due to mixed-content /
private-network browser restrictions. The native studio serves the same HTML
and JS from FastAPI at one origin, avoiding CORS exemptions and hardcoded
API credentials. There is no automatic media upload from public Pages.
Local Wi-Fi HTTP remains unencrypted; use a private HTTPS tunnel or trusted
VPN if confidentiality is required.

See [the connection and safety guide](docs/bridge-workflow.md).

## Run locally on Windows **or** Linux

The same FastAPI/FFmpeg/OpenCV backend and responsive browser UI run on both
operating systems. Python 3.11+, FFmpeg and FFprobe are required. The default
server binds to **127.0.0.1 only**; use `--lan` plus a long
`MOVIE_MODIFY_TOKEN` when operating it from an iPhone on a private Wi-Fi.

**Windows 10/11** (PowerShell or Command Prompt):

```powershell
winget install --id Gyan.FFmpeg -e
# Restart your terminal so the ffmpeg command is recognized.
.\scripts\start-windows.cmd
```

**Linux (Ubuntu)**:

```bash
sudo apt install -y ffmpeg python3-venv
bash scripts/start-linux.sh
```

Both launchers set up a Python virtual environment on first run. Open
`http://127.0.0.1:8000` in your browser. For an iPhone on the same LAN,
start with the access token and `--lan` as described in
[Windows/Linux deployment](docs/windows-linux.md).

You can also run `python -m movie_modify --port 8000` from an activated
environment. The `--data-dir` option supports storage on Windows drives or
Linux mount points.

**GitHub Pages is separate.** It runs static browser-side editing in `docs/`
without a local PC, but cannot invoke the native FFmpeg/OpenCV backend.
The local server provides the full analysis/tracking/high-quality rendering
features. Automatic syncing between Pages and the local server is not yet
implemented.

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

This is an **appearance tracker, not verified child identification**: other people, camera shake, changing lighting, seam crossings or temporary occlusion can cause tracking drift. Check the resulting camera trajectory before export. Each tracking job is limited to 20 minutes; longer footage is split into segments first. The in-editor 360° WebGL viewport now previews moving camera paths continuously, while final high-quality export is generated by FFmpeg.

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
- The low-resolution WebGL preview supports moving 360° viewpoints; the final FFmpeg render may differ slightly in fidelity or crop precision.
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
simultaneous editing now rejects stale server saves (HTTP 409), but no automatic merge is provided. Finish
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
