# Movie Modify Pages edition

> **[統合仕様書（全モード共通・日本語）](SPECIFICATION.md)** が最新の正本です。Pagesだけでなく、Windows/LinuxローカルStudio、人物追尾、API、編集JSONの仕様も一括して記載しています。

- Open `index.html` in a local HTTP server, or publish this `docs/` directory with GitHub Pages.
- Load a normal smartphone MP4/MOV, or a stitched equirectangular 2:1 MP4.
- Edit cut/keep intervals, reframe 360° footage with yaw/pitch/FOV keyframes, and preview the result continuously.
- Export project JSON non-destructively. JSON contains timestamps/view keyframes but **not** the source video; to reopen, reselect the source video.
- On supported browsers only, experimental real-time MediaRecorder export is available. Codec, audio, render quality and long-recording stability depend on the browser. Keep the project JSON and original source as backups.
- Camera-specific proprietary footage, FFmpeg/Auto-Editor analyses, and the OpenCV automatic person tracker require the local Python application. They cannot run on static GitHub Pages.
- File selection creates only a browser blob URL. The code uses no CDN, tracking, uploads, or remote media API. GitHub Pages itself is public, so do not commit personal video to the repository.

## Publish

If Pages is not already enabled, open the GitHub repository **Settings > Pages**. Set **Build and deployment > Deploy from a branch** and select `main /docs` or `main / (root)`. The root file redirects to `docs/`. GitHub Pages requires repository admin configuration; committing this static site does not automatically enable hosting.

Expected public address after deployment: `https://kameusagiyahoo.github.io/movie_modify/` (or `/docs/` on root publication). Actual availability depends on GitHub Pages settings and deployment.