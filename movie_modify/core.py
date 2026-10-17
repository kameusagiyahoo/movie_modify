"""Camera-independent edit decision list (EDL) and interval helpers.

All times are seconds in the *source* timeline, not the shortened output.
"""
from __future__ import annotations

import math
from fractions import Fraction


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def fresh_segment(start: float, end: float, *, suggested: bool = False) -> dict:
    return {"start": round(start, 3), "end": round(end, 3), "keep": True,
            "yaw": 0.0, "pitch": 0.0, "fov": 90.0,
            "suggested": suggested}


def normalize_segments(segments: list[dict], duration: float) -> list[dict]:
    """Validate edits and preserve gaps as implicit cuts (non-destructive)."""
    if not isinstance(segments, list) or not 1 <= len(segments) <= 5000:
        raise ValueError("Segments must contain between 1 and 5000 entries")
    if duration <= 0 or not math.isfinite(duration):
        raise ValueError("Invalid source duration")
    result = []
    last_end = 0.0
    for item in segments:
        if not isinstance(item, dict):
            raise ValueError("Invalid segment")
        try:
            start, end = float(item["start"]), float(item["end"])
            yaw, pitch, fov = [float(item.get(k, d)) for k, d in (("yaw", 0), ("pitch", 0), ("fov", 90))]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid segment value") from exc
        if not all(map(math.isfinite, (start, end, yaw, pitch, fov))):
            raise ValueError("Segment values must be finite")
        if start < -0.001 or end > duration + 0.05 or end - start < 0.04:
            raise ValueError("Segment range outside source duration")
        if start < last_end - 0.002:
            raise ValueError("Segments must be ordered and non-overlapping")
        if not -180 <= yaw <= 180 or not -90 <= pitch <= 90 or not 35 <= fov <= 140:
            raise ValueError("Invalid 360 viewing angle")
        if type(item.get("keep", True)) is not bool:
            raise ValueError("keep must be boolean")
        result.append({"start": round(max(0, start), 3), "end": round(min(end, duration), 3),
                       "keep": item.get("keep", True), "yaw": yaw, "pitch": pitch,
                       "fov": fov, "suggested": bool(item.get("suggested", False))})
        last_end = end
    return result


def merge_intervals(intervals: list[tuple[float, float]], duration: float, min_length: float = 0) -> list[dict]:
    clean = sorted((max(0.0, float(a)), min(duration, float(b))) for a, b in intervals
                   if math.isfinite(float(a)) and math.isfinite(float(b)) and b - a >= min_length)
    merged: list[list[float]] = []
    for start, end in clean:
        if end <= start:
            continue
        if merged and start <= merged[-1][1] + 0.15:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [{"start": round(a, 3), "end": round(b, 3), "reason": "quiet_audio"} for a, b in merged]


def apply_suggestions(segments: list[dict], suggestions: list[dict], indices: list[int], duration: float) -> list[dict]:
    """Split current intervals at selected suggestion boundaries, preserving view settings."""
    chosen = [suggestions[i] for i in indices if isinstance(i, int) and 0 <= i < len(suggestions)]
    boundaries = sorted(set([float(p) for x in chosen for p in (x["start"], x["end"])]))
    output = []
    for segment in normalize_segments(segments, duration):
        stops = [segment["start"]] + [t for t in boundaries if segment["start"] + .001 < t < segment["end"] - .001] + [segment["end"]]
        for a, b in zip(stops, stops[1:]):
            new = dict(segment, start=a, end=b)
            if any(a >= float(x["start"]) - .001 and b <= float(x["end"]) + .001 for x in chosen):
                new["keep"] = False
                new["suggested"] = True
            output.append(new)
    return normalize_segments(output, duration)


def parse_auto_editor_v1(data: dict, duration: float) -> list[dict]:
    """Auto-Editor V1 chunks: [start frame, end frame, speed], where 0 means cut."""
    if str(data.get("version")) != "1":
        raise ValueError("Expected Auto-Editor v1 timeline")
    fps = float(Fraction(str(data["timebase"])))
    if fps <= 0 or not math.isfinite(fps):
        raise ValueError("Invalid timebase")
    ranges = []
    for chunk in data["chunks"]:
        a, b, speed = chunk
        if float(speed) == 0:
            ranges.append((float(a) / fps, float(b) / fps))
    return merge_intervals(ranges, duration, min_length=1)
