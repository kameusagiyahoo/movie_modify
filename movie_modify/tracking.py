"""Optional offline appearance tracker for stitched 360 videos.

The user selects a target on the panorama. Template correlation / OpenCV CSRT
tracks appearance, NOT verified identity. Motion/occlusion may cause drift.
"""
from __future__ import annotations

import math
import subprocess


def track_panorama(source, start: float, end: float, x: float, y: float,
                   box: float = .10, fps: int = 4, callback=None):
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("pip install -r requirements-tracking.txt") from exc
    if not (0 <= x <= 1 and .02 <= y <= .98 and .04 <= box <= .24):
        raise ValueError("Invalid target")
    if not (.25 <= end - start <= 1200):
        raise ValueError("Track segments of 0.25–1200 seconds")
    w, h = 960, 480
    bw, bh = max(22, round(w * box)), max(22, round(h * min(.6, 2 * box)))
    cx, cy = x * w, y * h
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", str(start),
               "-i", str(source), "-t", str(end-start),
               "-vf", f"fps={fps},scale={w}:{h}", "-an",
               "-pix_fmt", "bgr24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            bufsize=w*h*3)
    tracker = None
    csrt = getattr(cv2, "TrackerCSRT_create", None)
    if csrt is None and hasattr(cv2, "legacy"):
        csrt = getattr(cv2.legacy, "TrackerCSRT_create", None)
    template, points = None, []
    bad, bad_run, max_bad = 0, 0, 0
    try:
        for i in range(math.ceil((end-start)*fps)):
            raw = proc.stdout.read(w*h*3)
            if len(raw) != w*h*3:
                break
            frame = np.frombuffer(raw, np.uint8).reshape(h,w,3)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            tiled = np.concatenate((gray,gray,gray), axis=1)
            if i == 0:
                left = round(cx+w-bw/2)
                top = max(0, min(h-bh, round(cy-bh/2)))
                template = tiled[top:top+bh,left:left+bw].copy()
                if csrt:
                    try:
                        tracker = csrt()
                        tripled = np.concatenate((frame,frame,frame),axis=1)
                        tracker.init(tripled,(left,top,bw,bh))
                    except Exception:
                        tracker = None
            else:
                success = False
                if tracker:
                    try:
                        tripled = np.concatenate((frame,frame,frame),axis=1)
                        ok, rect = tracker.update(tripled)
                        if ok:
                            px,py,ww,hh = rect
                            if 0 <= py+hh/2 <= h:
                                cx,cy = (px+ww/2)%w, py+hh/2
                                success = True
                    except Exception:
                        tracker = None
                if not success:
                    prev = cx + w
                    radius = max(70,bw*2)
                    x0 = max(0, round(prev-bw/2-radius))
                    x1 = min(3*w, round(prev+bw/2+radius))
                    y0 = max(0, round(cy-bh/2-radius))
                    y1 = min(h, round(cy+bh/2+radius))
                    region = tiled[y0:y1,x0:x1]
                    if region.shape[0]>=bh and region.shape[1]>=bw:
                        scores = cv2.matchTemplate(region,template,cv2.TM_CCOEFF_NORMED)
                        _,score,_,pos = cv2.minMaxLoc(scores)
                        if math.isfinite(score) and score >= .53:
                            cx = (x0+pos[0]+bw/2)%w
                            cy = y0+pos[1]+bh/2
                            bad_run=0
                            success=True
                            if score>=.8:
                                left=round(cx+w-bw/2)
                                top=round(cy-bh/2)
                                patch=tiled[top:top+bh,left:left+bw]
                                if patch.shape==template.shape:
                                    template=cv2.addWeighted(template,.97,patch,.03,0)
                    if not success:
                        bad+=1
                        bad_run+=1
                        max_bad=max(max_bad,bad_run)
            now = min(end,start+i/fps)
            points.append({"time":round(now,4), "yaw":round((cx/w-.5)*360,4),
                           "pitch":round(max(-85,min(85,(.5-cy/h)*180)),4),
                           "fov":90.0})
            if callback and i%(fps*2)==0:
                callback(min(88,round(88*(now-start)/(end-start))))
        if not points:
            raise RuntimeError("Unable to decode footage for tracking")
        points[0]["time"]=round(start,4)
        if points[-1]["time"]<end:
            points.append({**points[-1],"time":round(end,4)})
    finally:
        if proc.stdout:
            proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    warning=(f"追尾推定が不安定（{bad}フレーム）。対象が隠れる場面や類似する人物に注意してください。"
             if bad else "")
    return points,warning
