import os
import glob
import json
import textwrap
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import VideoFileClip, ImageClip, CompositeVideoClip, concatenate_videoclips, AudioFileClip, VideoClip, AudioArrayClip

from ken_burns_patch import make_ken_burns_clip, build_looping_background_kb
# ── CONFIG ──────────────────────────────────────────────
FOLDER    = r"E:\OPAL"
CHAT_FILE = r"E:\OPAL\temporarily_maintaining_the_conversation.txt"
OUTPUT    = r"E:\OPAL\OPAL_EPISODE.mp4"
NARRATION = r"E:\OPAL\narration.mp3"
MODEM_SFX = r"E:\OPAL\modem.mp3"
W, H      = 1280, 720
FPS       = 24
FOOTAGE_TRIM_START = 10.0  # seconds to skip at start of footage

# Max video clips to load (keeps memory manageable)
MAX_CLIPS = 4

# Intro timing
INTRO_ANIMATE = 6.2    # seconds of animation (matches modem.mp3)
INTRO_HOLD    = 3.0    # seconds to hold completed logo before main video
INTRO_DUR     = INTRO_ANIMATE + INTRO_HOLD  # total intro duration

# Outro duration (must be >= 4.0 for fade in/hold/fade out)
OUTRO_DUR = 4.0

# Pause between speakers in narrate.py (must match PAUSE_MS / 1000)
PAUSE_SEC = 1.0
# ────────────────────────────────────────────────────────

GREEN     = (57, 255, 20)
GREEN_DIM = (0, 210, 80)

def get_duration(path):
    c = AudioFileClip(path)
    d = c.duration
    c.close()
    return d

# Font cache — loaded once, reused every frame (avoid disk hit per frame)
_font_cache = {}

def get_font(size=16):
    if size not in _font_cache:
        for name in ["cour.ttf", "courbd.ttf", "Courier New.ttf"]:
            try:
                _font_cache[size] = ImageFont.truetype(name, size)
                break
            except:
                pass
        if size not in _font_cache:
            _font_cache[size] = ImageFont.load_default()
    return _font_cache[size]

def wrap_lines(text, width):
    """
    Returns:
      lines         — flat list of (text, color) tuples
      font          — the font used
      turn_line_idx — list of line indices where each turn starts (one per RAY:/AI: block)
    """
    font = get_font(22)
    chars = max(1, (width - 40) // 13)
    RAY_COLOR = (100, 160, 255)
    AI_COLOR  = (0, 255, 70)
    lines = []
    turn_line_idx = []   # line index where each turn begins
    speaker = None
    for raw in text.splitlines():
        s = raw.strip()
        if not s or s == "---":
            continue
        if s.startswith("RAY:"):
            turn_line_idx.append(len(lines))   # record turn start
            speaker = "RAY"
            lines.append(("RAY:", RAY_COLOR))
            rest = s[4:].strip()
            if rest:
                for l in textwrap.wrap(rest, chars):
                    lines.append((l, RAY_COLOR))
        elif s.startswith("AI:"):
            turn_line_idx.append(len(lines))   # record turn start
            speaker = "AI"
            lines.append(("AI:", AI_COLOR))
            rest = s[3:].strip()
            if rest:
                for l in textwrap.wrap(rest, chars):
                    lines.append((l, AI_COLOR))
        else:
            color = RAY_COLOR if speaker == "RAY" else AI_COLOR
            for l in textwrap.wrap(s, chars):
                lines.append((l, color))
    return lines, font, turn_line_idx

def sidebar_frame(lines, font, w, h, scroll_px):
    lh = 28
    img = Image.new("RGBA", (w, h), (0, 0, 0, 180))
    draw = ImageDraw.Draw(img)
    # Only draw lines that are actually on screen
    first = max(0, int((scroll_px - h) // lh))
    last  = min(len(lines), int(scroll_px // lh) + 2)
    for i in range(first, last):
        line, color = lines[i]
        y = (i * lh) - scroll_px + h
        if 0 <= y < h:
            draw.text((10, y), line, font=font, fill=color)
    return np.array(img)

def fit_image(path, duration):
    img = Image.open(path).convert("RGB")
    r = img.width / img.height
    nw, nh = (int(H * r), H) if r > W/H else (W, int(W / r))
    img = img.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - W) // 2, (nh - H) // 2
    return ImageClip(np.array(img.crop((x, y, x+W, y+H)))).with_duration(duration)

def build_looping_background(vids, imgs, dur):
    base_clips = []
    for v in vids:
        base_clips.append(VideoFileClip(v).resized((W, H)))

    if not base_clips and imgs:
        per = dur / len(imgs)
        return concatenate_videoclips([fit_image(i, per) for i in imgs], method="compose")

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

    print(f"  Background: {len(looped)} clip segments from {len(base_clips)} source clips")
    return concatenate_videoclips(looped, method="compose")

# ── SCROLL ANCHOR BUILDER ────────────────────────────────

def build_scroll_anchors(timing_turns, turn_line_idx, total_lines, lh=28):
    """
    Build a list of (time, scroll_px) anchor points — one per turn,
    plus a final anchor at the end of the last turn so scroll
    continues through the last speaker instead of freezing.

    scroll_px is calculated so the turn's first line sits ~2/3 up
    the sidebar panel, giving context above and below what's spoken.
    Formula: y = line_index * lh - scroll_px + H
    For y = H * 0.33 (2/3 up): scroll_px = line_index * lh + int(H * 0.67)
    """
    VPOS = int(H * 0.67)   # vertical position target: 0=top, H=bottom
    anchors = []
    n = min(len(timing_turns), len(turn_line_idx))
    for i in range(n):
        t_start  = timing_turns[i]["start"]
        line_idx = turn_line_idx[i]
        px       = line_idx * lh + VPOS
        anchors.append((t_start, float(px)))

    # Final anchor: end of last turn, scroll to bottom of content
    if timing_turns:
        t_end  = timing_turns[-1]["end"]
        px_end = float(total_lines * lh + VPOS)
        anchors.append((t_end, px_end))

    return anchors

def scroll_px_at(t, anchors):
    """
    Given time t and anchor list, return interpolated scroll_px.
    Before first anchor: hold at first anchor value.
    After last anchor:   hold at last anchor value.
    Between anchors:     linear interpolation.
    """
    if not anchors:
        return 0.0
    if t <= anchors[0][0]:
        return anchors[0][1]
    if t >= anchors[-1][0]:
        return anchors[-1][1]
    # Find surrounding pair
    for i in range(len(anchors) - 1):
        t0, px0 = anchors[i]
        t1, px1 = anchors[i + 1]
        if t0 <= t <= t1:
            frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return px0 + frac * (px1 - px0)
    return anchors[-1][1]

# ── INTRO ────────────────────────────────────────────────

def make_intro_frame(t, title):
    """
    Terminal boot sequence:
    0-0.5s:    black
    0.5-2s:    border box draws in
    2-3.5s:    OPAL types in
    3.5-4.5s:  divider + subtitle appear
    4.5-5.5s:  hash border rows appear
    5.5-6.2s:  episode title types in with blinking cursor
    6.2-9.2s:  logo holds fully visible (INTRO_HOLD)
    """
    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_lg  = get_font(64)
    font_med = get_font(20)
    font_sm  = get_font(16)

    cx = W // 2
    box_w, box_h = 420, 220
    bx = (W - box_w) // 2
    by = (H - box_h) // 2

    # Border box draws in
    if t >= 0.5:
        progress = min(1.0, (t - 0.5) / 1.5)
        perimeter = 2 * (box_w + box_h)
        drawn = int(perimeter * progress)
        top = min(drawn, box_w)
        if top > 0:
            draw.line([(bx, by), (bx + top, by)], fill=GREEN_DIM, width=1)
        drawn -= top
        right = min(max(0, drawn), box_h)
        if right > 0:
            draw.line([(bx + box_w, by), (bx + box_w, by + right)], fill=GREEN_DIM, width=1)
        drawn -= right
        bottom = min(max(0, drawn), box_w)
        if bottom > 0:
            draw.line([(bx + box_w, by + box_h), (bx + box_w - bottom, by + box_h)], fill=GREEN_DIM, width=1)
        drawn -= bottom
        left = min(max(0, drawn), box_h)
        if left > 0:
            draw.line([(bx, by + box_h), (bx, by + box_h - left)], fill=GREEN_DIM, width=1)

    # OPAL types in
    if t >= 2.0:
        chars_shown = min(4, int((t - 2.0) / 0.35) + 1)
        opal_text = "OPAL"[:chars_shown]
        bbox = draw.textbbox((0, 0), "OPAL", font=font_lg)
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, by + 28), opal_text, font=font_lg, fill=GREEN)

    # Divider + subtitle
    if t >= 3.5:
        div_y = by + 100
        draw.line([(bx + 20, div_y), (bx + box_w - 20, div_y)], fill=GREEN_DIM, width=1)
        subtitle = "Open Peripatetic Audit Log"
        bbox = draw.textbbox((0, 0), subtitle, font=font_med)
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, div_y + 10), subtitle, font=font_med, fill=GREEN_DIM)

    # Hash border rows
    if t >= 4.5:
        hashes = "▓" * 40
        bbox = draw.textbbox((0, 0), hashes, font=font_sm)
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, by + 10), hashes, font=font_sm, fill=GREEN_DIM)
        draw.text((cx - tw // 2, by + box_h - 22), hashes, font=font_sm, fill=GREEN_DIM)

    # Episode title types in, then holds
    if t >= 5.5:
        chars_shown = min(len(title), int((t - 5.5) * 20))
        title_partial = title[:chars_shown]
        # cursor blinks during typing, disappears during hold
        cursor = "_" if (t < INTRO_ANIMATE and int(t * 2) % 2 == 0) else ""
        display = title_partial + cursor
        bbox = draw.textbbox((0, 0), title, font=font_med)
        tw = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, by + 145), display, font=font_med, fill=GREEN)

    return np.array(img)

def build_intro(title):
    print(f"  Building intro ({INTRO_DUR:.1f}s) — episode: {title}")
    clip = VideoClip(lambda t: make_intro_frame(t, title), duration=INTRO_DUR).with_fps(FPS)
    if os.path.exists(MODEM_SFX):
        modem = AudioFileClip(MODEM_SFX)
        if modem.duration > INTRO_DUR:
            modem = modem.subclipped(0, INTRO_DUR)
        clip = clip.with_audio(modem)
        print(f"  Modem SFX loaded: {MODEM_SFX}")
    else:
        print(f"  No modem SFX found at {MODEM_SFX} — intro will be silent")
    return clip

# ── OUTRO TONE ───────────────────────────────────────────

def make_outro_tone(duration, sample_rate=44100):
    """Generate a carrier-drop tone: static burst then 800hz fading to silence."""
    t = np.linspace(0, duration, int(sample_rate * duration))

    # 800hz carrier tone fading out
    fade = np.exp(-2.5 * t)
    tone = np.sin(2 * np.pi * 800 * t) * fade * 0.4

    # Brief static burst at the start (0 to 0.25s)
    static_samples = int(sample_rate * 0.25)
    static = np.random.uniform(-0.3, 0.3, static_samples)
    static *= np.linspace(0.6, 0, static_samples)
    tone[:static_samples] += static

    # Normalize and make stereo
    peak = np.max(np.abs(tone))
    if peak > 0:
        tone = tone / peak * 0.75
    stereo = np.column_stack([tone, tone]).astype(np.float32)
    return AudioArrayClip(stereo, fps=sample_rate)

# ── OUTRO ────────────────────────────────────────────────

def make_outro_frame(t):
    """Fade in END OF TRANSMISSION, hold, fade to black."""
    img = Image.new("RGB", (W, H), (0, 0, 0))
    draw = ImageDraw.Draw(img)
    font_med = get_font(20)
    if t < 1.0:
        alpha = t
    elif t < 3.0:
        alpha = 1.0
    else:
        alpha = max(0.0, 1.0 - (t - 3.0))

    color = (int(0 * alpha), int(255 * alpha), int(70 * alpha))
    msg = "[ END OF TRANSMISSION ]"
    bbox = draw.textbbox((0, 0), msg, font=font_med)
    tw = bbox[2] - bbox[0]
    draw.text((W // 2 - tw // 2, H // 2 - 10), msg, font=font_med, fill=color)
    return np.array(img)

def build_outro():
    print(f"  Building outro ({OUTRO_DUR}s) with carrier-drop tone...")
    clip = VideoClip(make_outro_frame, duration=OUTRO_DUR).with_fps(FPS)
    tone = make_outro_tone(OUTRO_DUR)
    return clip.with_audio(tone)

# ── MAIN ─────────────────────────────────────────────────

def fuse():
    print("\n=== OPAL FUSION ===\n")

    if not os.path.exists(NARRATION):
        print("ERROR: No narration.mp3 found. Run narrate.py first.")
        return

    # Derive episode title from filename
    title = os.path.basename(CHAT_FILE).replace("_opal.txt", "").replace(".txt", "").replace("_", " ").upper()
    print(f"  Episode: {title}")

    # Load timing.json
    timing_path = os.path.join(FOLDER, "timing.json")
    timing_turns = []
    num_turns = 0
    if os.path.exists(timing_path):
        with open(timing_path) as f:
            timing = json.load(f)
        dur = timing["total_duration"]
        timing_turns = timing["turns"]
        num_turns = len(timing_turns)
        print(f"  Narration: {dur:.1f}s ({dur/60:.1f}m)  [from timing.json, {num_turns} turns]")
    else:
        dur = get_duration(NARRATION)
        print(f"  Narration: {dur:.1f}s ({dur/60:.1f}m)  [from audio file — no timing.json, using linear scroll]")

    seen = set()
    imgs = []
    for ext in ["*.jpg", "*.jpeg", "*.png"]:
        for f in glob.glob(os.path.join(FOLDER, ext)):
            n = os.path.basename(f).lower()
            if n not in seen:
                seen.add(n)
                imgs.append(f)

    vids = sorted([f for f in glob.glob(os.path.join(FOLDER, "*.mp4")) + 
               glob.glob(os.path.join(FOLDER, "*.webm"))
               if "OPAL_" not in os.path.basename(f).upper()])[:MAX_CLIPS]
    print(f"  Footage: {len(vids)} videos (capped at {MAX_CLIPS}), {len(imgs)} images")

    if not vids and not imgs:
        print("ERROR: No footage found.")
        return

    # Build sections
    intro   = build_intro(title)
    outro   = build_outro()
    main_bg = build_looping_background_kb(vids, imgs, dur, W, H, FPS)
    if main_bg.duration > dur:
        main_bg = main_bg.subclipped(FOOTAGE_TRIM_START, FOOTAGE_TRIM_START + dur)
    fdur = main_bg.duration
    print(f"  Main video: {fdur:.1f}s")

    # ── Sidebar scroll
    txt = open(CHAT_FILE, encoding="utf-8").read() if os.path.exists(CHAT_FILE) else ""
    sw = W // 3
    lines, font, turn_line_idx = wrap_lines(txt, sw)

    lh = 28
    total_content = len(lines) * lh
    print(f"  Scroll: {len(lines)} lines, {total_content}px content")

    if timing_turns and turn_line_idx:
        # ── TIMING-DRIVEN SCROLL ──────────────────────────────
        # Warn if counts don't match (mismatch = stale timing.json)
        if len(timing_turns) != len(turn_line_idx):
            print(f"  WARNING: timing.json has {len(timing_turns)} turns but transcript has "
                  f"{len(turn_line_idx)} turns — they may be out of sync. Re-run narrate.py if scroll looks wrong.")

        anchors = build_scroll_anchors(timing_turns, turn_line_idx, len(lines), lh)
        print(f"  Scroll mode: timing-driven ({len(anchors)} anchors)")
        print(f"  First anchor: t={anchors[0][0]:.1f}s → px={anchors[0][1]:.0f}")
        print(f"  Last  anchor: t={anchors[-1][0]:.1f}s → px={anchors[-1][1]:.0f}")

        def make_sidebar_frame(t):
            px = scroll_px_at(t, anchors)
            return sidebar_frame(lines, font, sw, H, px)

    else:
        # ── FALLBACK: LINEAR SCROLL ───────────────────────────
        print(f"  Scroll mode: linear fallback (no timing.json or no turn markers)")
        pause_total = max(0, (num_turns - 1)) * PAUSE_SEC
        scroll_dur  = max(1.0, fdur - pause_total)
        scroll_start = float(H)                          # first line enters from bottom
        scroll_end   = float(total_content + H)
        travel       = scroll_end - scroll_start
        print(f"  Speed: {travel/scroll_dur:.1f} px/sec")

        def make_sidebar_frame(t):
            progress = min(1.0, t / scroll_dur)
            px = scroll_start + progress * travel
            return sidebar_frame(lines, font, sw, H, px)

    sidebar = (
        VideoClip(make_sidebar_frame, duration=fdur)
        .with_position(("right", "top"))
        .with_fps(FPS)
    )

    audio = AudioFileClip(NARRATION)
    main_video = CompositeVideoClip([main_bg, sidebar]).with_audio(audio)

    # Concatenate intro + main + outro
    final = concatenate_videoclips([intro, main_video, outro], method="compose")

    print("\nRendering...\n")
    final.write_videofile(OUTPUT, fps=FPS, codec="libx264", audio_codec="aac", threads=4, logger="bar")
    print(f"\n✓ DONE: {OUTPUT}\n")
    print(f"  Total duration: {final.duration:.1f}s ({final.duration/60:.1f}m)")

if __name__ == "__main__":
    fuse()
