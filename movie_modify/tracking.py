"""Conservative offline appearance tracker for stitched 360° videos.

The user selects an initial subject. OpenCV CSRT is only a proposal: its
position is verified against an immutable appearance reference. On likely
occlusion, freeze the last reliable camera pose instead of following drift.
Reacquisition uses a gradually widening *local* panorama search, plus an
ambiguity test; it is not face recognition or an identity guarantee.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass


@dataclass
class RecoveryState:
    """Pure-Python policy, testable without NumPy/OpenCV or real recordings."""
    missed: int = 0
    lost_frames: int = 0
    max_lost_run: int = 0
    recovered: int = 0
    rejected_ambiguous: int = 0

    def radius(self, base: int, image_width: int) -> int:
        # Never search the entire 360° panorama solely to find someone similar.
        return min(round(image_width * .45),
                   round(base * (1 + min(self.missed, 30) * .32)))

    def accepts(self, confidence: float, reference: float,
                runner_up: float | None = None, *, csrt: bool = False) -> bool:
        if not (math.isfinite(confidence) and math.isfinite(reference)):
            return False
        # Stronger evidence is required after losing the person, especially
        # after a long occlusion. CSRT is not blindly trusted.
        threshold = (.54 if csrt else .65) if self.missed == 0 else (
            .73 if self.missed < 6 else .82
        )
        if confidence < threshold or reference < (.44 if self.missed == 0 else .57):
            return False
        if self.missed and runner_up is not None and math.isfinite(runner_up):
            if confidence - runner_up < .055:
                self.rejected_ambiguous += 1
                return False
        return True

    def advance(self, found: bool) -> str:
        if found:
            was_lost = self.missed > 0
            if was_lost:
                self.recovered += 1
            self.missed = 0
            return "recovered" if was_lost else "tracked"
        self.missed += 1
        self.lost_frames += 1
        self.max_lost_run = max(self.max_lost_run, self.missed)
        return "lost"

    def warning(self, frame_rate: float) -> str:
        if not self.lost_frames and not self.rejected_ambiguous:
            return ""
        lost = self.lost_frames / max(frame_rate, 1)
        max_gap = self.max_lost_run / max(frame_rate, 1)
        return (
            f"追尾が不安定です（未検出 {self.lost_frames}フレーム／約{lost:.1f}秒、"
            f"最長連続{max_gap:.1f}秒、再発見{self.recovered}回、"
            f"曖昧な候補の拒否{self.rejected_ambiguous}回）。"
            "未検出時は直前の画角を維持しました。"
            "似た人物・遮蔽・カメラのつなぎ目を再生して手動確認してください。"
        )


def _match_in_region(cv2, np, tiled, template, center_x, center_y,
                     radius, width, height):
    """Best and second separated peaks for ambiguous-candidate rejection."""
    bh, bw = template.shape
    x0 = max(0, round(center_x + width - bw / 2 - radius))
    x1 = min(3 * width, round(center_x + width + bw / 2 + radius))
    y0 = max(0, round(center_y - bh / 2 - radius))
    y1 = min(height, round(center_y + bh / 2 + radius))
    region = tiled[y0:y1, x0:x1]
    if region.shape[0] < bh or region.shape[1] < bw:
        return None
    scores = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    _low, best, _min_pos, pos = cv2.minMaxLoc(scores)
    if not math.isfinite(float(best)):
        return None
    # Exclude nearby matches to the same physical person before inspecting
    # another separate candidate. This is conservative for repeated patterns.
    runner_up = None
    if scores.shape[0] > bh // 2 or scores.shape[1] > bw // 2:
        alternative = scores.copy()
        px, py = pos
        rx, ry = max(3, bw // 2), max(3, bh // 2)
        alternative[max(0, py-ry):py+ry+1,
                    max(0, px-rx):px+rx+1] = -1.0
        _lo, second, _mp, _sp = cv2.minMaxLoc(alternative)
        if second >= 0 and math.isfinite(float(second)):
            runner_up = float(second)
    return ((x0 + pos[0] + bw/2) % width, y0 + pos[1] + bh/2,
            float(best), runner_up)


def _reference_score(cv2, np, tiled, anchor, x, y, width, height):
    bh, bw = anchor.shape
    left = round((x % width) + width - bw / 2)
    top = max(0, min(height-bh, round(y - bh / 2)))
    patch = tiled[top:top+bh, left:left+bw]
    if patch.shape != anchor.shape:
        return -1.0
    # A textureless box gives uninformative normalized correlations.
    if float(np.std(anchor)) < 3 or float(np.std(patch)) < 3:
        return -1.0
    score = cv2.matchTemplate(patch, anchor, cv2.TM_CCOEFF_NORMED)[0, 0]
    return float(score) if math.isfinite(float(score)) else -1.0


def track_panorama(source, start: float, end: float, x: float, y: float,
                   box: float = .10, fps: int = 4, callback=None, *, include_diagnostics=False):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("pip install -r requirements-tracking.txt") from exc
    if not (0 <= x <= 1 and .02 <= y <= .98 and .04 <= box <= .24):
        raise ValueError("Invalid target")
    if not (.25 <= end - start <= 1200) or not 1 <= fps <= 30:
        raise ValueError("Track segments of 0.25–1200 seconds, 1–30 FPS")
    w, h = 960, 480
    bw, bh = max(22, round(w * box)), max(22, round(h * min(.6, 2 * box)))
    cx, cy = float(x * w), float(y * h)
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(start),
               "-i", str(source), "-t", str(end-start),
               "-vf", f"fps={fps},scale={w}:{h}", "-an",
               "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=w*h*3)
    if proc.stdout is None:
        raise RuntimeError("FFmpeg pipe for tracking not available")
    factory = getattr(cv2, "TrackerCSRT_create", None)
    if factory is None and hasattr(cv2, "legacy"):
        factory = getattr(cv2.legacy, "TrackerCSRT_create", None)
    tracker = None
    anchor = None
    adaptive = None
    frames = []
    state = RecoveryState()
    gaps: list[dict] = []
    lost_from: float | None = None

    def make_tracker(frame, xcoord, ycoord):
        if not factory:
            return None
        left = round(xcoord+w-bw/2)
        top = max(0, min(h-bh, round(ycoord-bh/2)))
        try:
            instance = factory()
            instance.init(np.concatenate((frame,frame,frame),axis=1),
                          (left,top,bw,bh))
            return instance
        except Exception:
            return None

    try:
        for index in range(math.ceil((end-start)*fps)):
            raw = proc.stdout.read(w*h*3)
            if len(raw) != w*h*3:
                break
            frame = np.frombuffer(raw, np.uint8).reshape(h,w,3)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            tiled = np.concatenate((gray,gray,gray), axis=1)
            if index == 0:
                left = round(cx+w-bw/2)
                top = max(0, min(h-bh, round(cy-bh/2)))
                anchor = tiled[top:top+bh,left:left+bw].copy()
                adaptive = anchor.copy()
                if anchor.shape != (bh,bw) or float(np.std(anchor)) < 3:
                    raise RuntimeError(
                        "Selected region has too little visual texture to track reliably"
                    )
                tracker = make_tracker(frame, cx, cy)
            else:
                candidate = None
                # Validate CSRT with the unchanged first-frame appearance
                # instead of assuming its internal success flag proves identity.
                if tracker and state.missed == 0:
                    try:
                        tripled = np.concatenate((frame,frame,frame),axis=1)
                        ok, rect = tracker.update(tripled)
                        if ok:
                            px, py, ww, hh = rect
                            x_try, y_try = (px+ww/2)%w, py+hh/2
                            if 0 <= y_try <= h:
                                similarity = _reference_score(
                                    cv2, np, tiled, anchor, x_try, y_try, w, h
                                )
                                if state.accepts(similarity, similarity, csrt=True):
                                    candidate = (x_try, y_try, similarity)
                    except Exception:
                        tracker = None

                # When CSRT confidence deteriorates, search near the last
                # reliable location (including wrap at the 360° seam).
                if candidate is None:
                    radius=state.radius(max(70, 2*bw), w)
                    proposal=_match_in_region(cv2,np,tiled,adaptive,
                                              cx,cy,radius,w,h)
                    if proposal is not None:
                        x_try, y_try, score, runner_up = proposal
                        anchor_score = _reference_score(
                            cv2,np,tiled,anchor,x_try,y_try,w,h
                        )
                        if state.accepts(score, anchor_score, runner_up):
                            candidate = (x_try, y_try, score)

                if candidate is not None:
                    old_missing=state.missed
                    cx, cy, confidence = candidate
                    if lost_from is not None:
                        gaps.append({"start": round(lost_from, 3),
                                     "end": round(min(end, start+index/fps), 3)})
                        lost_from = None
                    result=state.advance(True)
                    if result=="recovered" or tracker is None or old_missing>0:
                        tracker=make_tracker(frame,cx,cy)
                    # Slowly refresh only when the reference is still a
                    # strong match; it cannot alter the original anchor.
                    if confidence >= .84:
                        left=round(cx+w-bw/2)
                        top=max(0,min(h-bh,round(cy-bh/2)))
                        patch=tiled[top:top+bh,left:left+bw]
                        if patch.shape == adaptive.shape:
                            adaptive=cv2.addWeighted(adaptive,.985,patch,.015,0)
                else:
                    if lost_from is None:
                        lost_from = min(end, start+index/fps)
                    state.advance(False)
                    tracker=None
                    # cx/cy deliberately unchanged: freeze the last reliable
                    # view rather than producing arbitrary false track points.
            now=min(end,start+index/fps)
            frames.append({"time":round(now,4),
                           "yaw":round((cx/w-.5)*360,4),
                           "pitch":round(max(-85,min(85,(.5-cy/h)*180)),4),
                           "fov":90.0})
            if callback and index % max(1, fps*2) == 0:
                callback(min(88,round(88*(now-start)/(end-start))))
        if not frames:
            raise RuntimeError("Unable to decode footage for tracking")
        if lost_from is not None and lost_from < end:
            gaps.append({"start": round(lost_from, 3), "end": round(end, 3)})
        frames[0]["time"]=round(start,4)
        if frames[-1]["time"]<end:
            frames.append({**frames[-1],"time":round(end,4)})
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    if include_diagnostics:
        return frames, state.warning(fps), gaps
    return frames, state.warning(fps)
