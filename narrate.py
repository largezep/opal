import asyncio
import json
import os
import subprocess
import sys
import tempfile
import edge_tts
from moviepy import AudioFileClip

# ── CONFIG ──────────────────────────────────────────────
CHAT_FILE = r"E:\OPAL\equilibrium_of_exploitation_converted.txt"
AUDIO_OUT  = r"E:\OPAL\narration.mp3"
TIMING_OUT = r"E:\OPAL\timing.json"
FUSION     = r"E:\OPAL\fusion.py"

RAY_VOICE  = "en-US-GuyNeural"
AI_VOICE   = "en-GB-SoniaNeural"
PAUSE_MS   = 1000  # pause between speakers
# ────────────────────────────────────────────────────────

def parse_turns(filepath):
    turns = []
    current_speaker = None
    current_lines = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip()
            if line.startswith("RAY:"):
                if current_speaker and current_lines:
                    turns.append((current_speaker, " ".join(current_lines)))
                current_speaker = "RAY"
                current_lines = []
                rest = line[4:].strip()
                if rest:
                    current_lines.append(rest)
            elif line.startswith("AI:"):
                if current_speaker and current_lines:
                    turns.append((current_speaker, " ".join(current_lines)))
                current_speaker = "AI"
                current_lines = []
                rest = line[3:].strip()
                if rest:
                    current_lines.append(rest)
            elif line.strip() == "---":
                continue
            elif line.strip() and current_speaker:
                current_lines.append(line.strip())
    if current_speaker and current_lines:
        turns.append((current_speaker, " ".join(current_lines)))
    return turns


async def render_turn(text, voice, path):
    tts = edge_tts.Communicate(text, voice)
    await tts.save(path)


def get_mp3_duration(path):
    """Accurately measure MP3 duration using moviepy."""
    c = AudioFileClip(path)
    d = c.duration
    c.close()
    return d


def make_silence_frames(duration_ms):
    """Raw MP3 silent frames."""
    frame = bytes([0xFF, 0xFB, 0x90, 0x00] + [0x00] * 413)
    return frame * max(1, duration_ms // 26)


def concat_mp3s(segment_paths, output_path, pause_ms):
    silence = make_silence_frames(pause_ms)
    with open(output_path, 'wb') as out:
        for i, path in enumerate(segment_paths):
            with open(path, 'rb') as f:
                out.write(f.read())
            if i < len(segment_paths) - 1:
                out.write(silence)
    return os.path.getsize(output_path)


async def build_audio(turns, audio_path, timing_path):
    tmpdir = tempfile.mkdtemp()
    segment_paths = []

    print(f"\nRendering {len(turns)} turns...\n")
    for i, (speaker, text) in enumerate(turns):
        voice = RAY_VOICE if speaker == "RAY" else AI_VOICE
        seg_path = os.path.join(tmpdir, f"turn_{i:03d}.mp3")
        print(f"  [{i+1}/{len(turns)}] {speaker}: {text[:60]}{'...' if len(text)>60 else ''}")
        await render_turn(text, voice, seg_path)
        segment_paths.append(seg_path)

    # Build timing map using accurate durations
    pause_secs = PAUSE_MS / 1000.0
    timing = []
    cursor = 0.0
    for i, (seg_path, (speaker, text)) in enumerate(zip(segment_paths, turns)):
        dur = get_mp3_duration(seg_path)
        timing.append({"turn": i, "speaker": speaker, "start": round(cursor, 3),
                        "duration": round(dur, 3), "end": round(cursor + dur, 3)})
        print(f"    Turn {i} ({speaker}): {dur:.3f}s")
        cursor += dur + pause_secs

    total_dur = cursor - pause_secs
    print(f"\n  Total audio: {total_dur:.3f}s ({total_dur/60:.2f}m)")

    with open(timing_path, 'w') as f:
        json.dump({"turns": timing, "total_duration": round(total_dur, 3)}, f, indent=2)
    print(f"  Timing saved: {timing_path}")

    size = concat_mp3s(segment_paths, audio_path, PAUSE_MS)
    print(f"  Audio saved: {audio_path}  ({size//1024}kb)")
    return True


async def main():
    print("\n=== OPAL NARRATE ===\n")
    turns = parse_turns(CHAT_FILE)
    ray_n = sum(1 for s,_ in turns if s=="RAY")
    ai_n  = sum(1 for s,_ in turns if s=="AI")
    print(f"Found {len(turns)} turns  (RAY: {ray_n}, AI: {ai_n})\n")
    if not turns:
        print("No turns found.")
        return
    await build_audio(turns, AUDIO_OUT, TIMING_OUT)
    print("\n=== Launching OPAL FUSION ===\n")
    subprocess.run([sys.executable, FUSION])

if __name__ == "__main__":
    asyncio.run(main())
