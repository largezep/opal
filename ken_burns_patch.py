"""
ken_burns_patch.py
==================
Drop-in replacement for fit_image() in fusion.py and build_looping_background().

Adds slow Ken Burns effect (pan and zoom) to still images so they feel alive
rather than static holds.

HOW TO APPLY:
1. In fusion.py, replace the fit_image() function with make_ken_burns_clip() below
2. Replace the build_looping_background() function with the new version below
3. That's it — images now drift slowly instead of holding static

EFFECT OPTIONS (set per image or use random):
- zoom_in:   slow zoom from 100% to 115%
- zoom_out:  slow zoom from 115% to 100%
- pan_left:  slow pan left to right
- pan_right: slow pan right to left
- drift:     very slow diagonal drift (most cinematic for space)

For space/cosmology content, "drift" and "zoom_in" work best.
Random selection across images gives natural variety.
"""

import random
import os
import numpy as np
from moviepy import ImageClip, concatenate_videoclips, VideoClip, VideoFileClip
from PIL import Image
from moviepy import ImageClip, concatenate_videoclips

# Ken Burns config
KB_ZOOM_FACTOR = 1.3    # how much to zoom during effect (1.0 = no zoom, 1.2 = 20% zoom)
KB_OVERSCAN    = 1.35    # how much larger to make source image (must be >= KB_ZOOM_FACTOR)

# Effect choices for random selection
KB_EFFECTS = ["zoom_in", "zoom_out", "drift_right", "drift_left", "drift_up"]


def make_ken_burns_clip(path, duration, W, H, FPS, effect=None):
    """
    Load an image and apply a slow Ken Burns effect for the given duration.

    Args:
        path:     path to image file
        duration: clip duration in seconds
        W, H:     output dimensions
        FPS:      frames per second
        effect:   one of KB_EFFECTS, or None for random

    Returns:
        MoviePy ImageClip with smooth motion
    """
    if effect is None:
        effect = random.choice(KB_EFFECTS)

    # Load and prepare source image — larger than output so we can pan/zoom
    img = Image.open(path).convert("RGB")

    # Scale image to fit output with overscan for motion room
    target_w = int(W * KB_OVERSCAN)
    target_h = int(H * KB_OVERSCAN)

    r = img.width / img.height
    target_r = target_w / target_h

    if r > target_r:
        # Image is wider — fit height
        new_h = target_h
        new_w = int(new_h * r)
    else:
        # Image is taller — fit width
        new_w = target_w
        new_h = int(new_w / r)

    img = img.resize((new_w, new_h), Image.LANCZOS)
    src = np.array(img)

    src_h, src_w = src.shape[:2]

    def get_frame(t):
        """Generate a single frame at time t with Ken Burns motion."""
        progress = t / max(duration, 0.001)  # 0.0 to 1.0

        if effect == "zoom_in":
            # Start normal, zoom in slowly
            scale = 1.0 + (KB_ZOOM_FACTOR - 1.0) * progress
            crop_w = int(W / scale * (src_w / W))
            crop_h = int(H / scale * (src_h / H))
            # Center crop
            x = (src_w - crop_w) // 2
            y = (src_h - crop_h) // 2

        elif effect == "zoom_out":
            # Start zoomed in, zoom out slowly
            scale = KB_ZOOM_FACTOR - (KB_ZOOM_FACTOR - 1.0) * progress
            crop_w = int(W / scale * (src_w / W))
            crop_h = int(H / scale * (src_h / H))
            x = (src_w - crop_w) // 2
            y = (src_h - crop_h) // 2

        elif effect == "drift_right":
            # Pan slowly from left to right
            crop_w = int(W * src_w / (W * KB_OVERSCAN) * W / W)
            crop_w = W
            crop_h = H
            # Adjust for actual source size
            max_x = src_w - W
            max_y = src_h - H
            x = int(max_x * progress * 0.3)  # gentle drift
            y = max_y // 2

        elif effect == "drift_left":
            # Pan slowly from right to left
            max_x = src_w - W
            max_y = src_h - H
            x = max_x - int(max_x * progress * 0.3)
            y = max_y // 2
            crop_w = W
            crop_h = H

        elif effect == "drift_up":
            # Pan slowly upward
            max_x = src_w - W
            max_y = src_h - H
            x = max_x // 2
            y = max_y - int(max_y * progress * 0.3)
            crop_w = W
            crop_h = H

        else:
            # Fallback: center crop static
            x = (src_w - W) // 2
            y = (src_h - H) // 2
            crop_w = W
            crop_h = H

        # Clamp
        x = max(0, min(x, src_w - crop_w))
        y = max(0, min(y, src_h - crop_h))

        # Crop
        cropped = src[y:y+crop_h, x:x+crop_w]

        # Resize to exact output dimensions if needed
        if cropped.shape[1] != W or cropped.shape[0] != H:
            pil = Image.fromarray(cropped).resize((W, H), Image.LANCZOS)
            cropped = np.array(pil)

        return cropped

    clip = VideoClip(get_frame, duration=duration).with_fps(FPS)
    return clip


def build_looping_background_kb(vids, imgs, dur, W, H, FPS, MAX_CLIPS=4):
    """
    Replacement for build_looping_background() in fusion.py.
    Uses Ken Burns effect on images, loops videos as before.

    If both vids and imgs are present, interleaves them.
    If only imgs, uses Ken Burns across all of them.
    If only vids, behaves exactly like the original function.
    """
    import glob
    from moviepy import VideoFileClip

    # Images-only path (most common for OPAL cosmology)
    if imgs and not vids:
        print(f"  Ken Burns mode: {len(imgs)} images")
        effects = KB_EFFECTS * (len(imgs) // len(KB_EFFECTS) + 1)
        random.shuffle(effects)

        per_image = dur / len(imgs)
        clips = []
        for i, (img_path, effect) in enumerate(zip(imgs, effects)):
            print(f"  [{i+1}/{len(imgs)}] {os.path.basename(img_path)} — {effect} ({per_image:.1f}s)")
            clip = make_ken_burns_clip(img_path, per_image, W, H, FPS, effect)
            clips.append(clip)

        return concatenate_videoclips(clips, method="compose")

    # Videos-only path (same as original)
    if vids and not imgs:
        base_clips = [VideoFileClip(v).resized((W, H)) for v in vids[:MAX_CLIPS]]
        looped = []
        total = 0.0
        idx = 0
        while total < dur:
            clip = base_clips[idx % len(base_clips)]
            remaining = dur - total
            if clip.duration <= remaining:
                looped.append(clip)
                total += clip.duration
            else:
                looped.append(clip.subclipped(0, remaining))
                total = dur
            idx += 1
        print(f"  Video loop mode: {len(looped)} segments from {len(base_clips)} clips")
        return concatenate_videoclips(looped, method="compose")

    # Mixed: videos + images — interleave
    if vids and imgs:
        print(f"  Mixed mode: {len(vids)} videos + {len(imgs)} images")
        # Use videos first, then fill with Ken Burns images
        base_clips = [VideoFileClip(v).resized((W, H)) for v in vids[:MAX_CLIPS]]
        video_dur = sum(c.duration for c in base_clips)

        if video_dur >= dur:
            # Videos cover full duration — loop them
            looped = []
            total = 0.0
            idx = 0
            while total < dur:
                clip = base_clips[idx % len(base_clips)]
                remaining = dur - total
                if clip.duration <= remaining:
                    looped.append(clip)
                    total += clip.duration
                else:
                    looped.append(clip.subclipped(0, remaining))
                    total = dur
                idx += 1
            return concatenate_videoclips(looped, method="compose")
        else:
            # Videos don't cover full duration — add Ken Burns images for remainder
            remaining_dur = dur - video_dur
            per_image = remaining_dur / len(imgs)
            img_clips = [make_ken_burns_clip(p, per_image, W, H, FPS) for p in imgs]
            all_clips = base_clips + img_clips
            return concatenate_videoclips(all_clips, method="compose")

    return None


# Standalone test
if __name__ == "__main__":
    import os
    print("Ken Burns patch loaded successfully.")
    print(f"Effects available: {KB_EFFECTS}")
    print(f"Zoom factor: {KB_ZOOM_FACTOR}x")
    print(f"Overscan: {KB_OVERSCAN}x")
    print("\nTo apply: replace fit_image() and build_looping_background() in fusion.py")
    print("with make_ken_burns_clip() and build_looping_background_kb() from this file.")
