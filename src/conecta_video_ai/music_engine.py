from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


def _envelope(length: int, attack: float = 0.08, release: float = 0.18) -> np.ndarray:
    if length <= 0:
        return np.array([], dtype=np.float32)

    env = np.ones(length, dtype=np.float32)
    atk = max(1, int(length * attack))
    rel = max(1, int(length * release))

    env[:atk] = np.linspace(0.0, 1.0, atk, dtype=np.float32)
    env[-rel:] = np.linspace(1.0, 0.0, rel, dtype=np.float32)
    return env


def generate_instrumental_bed(
    *,
    duration_seconds: float,
    output_path: Path,
    sample_rate: int = 44100,
    seed: int = 42,
) -> Path:
    duration = max(4.0, float(duration_seconds))
    total_samples = int(duration * sample_rate)
    t = np.arange(total_samples, dtype=np.float32) / sample_rate

    rng = np.random.default_rng(seed)

    # Multiple progressions + tempo variation so each render has audible differences.
    progressions = [
        [(220.0, 277.18, 329.63), (196.0, 246.94, 293.66), (174.61, 220.0, 261.63), (196.0, 246.94, 293.66)],
        [(233.08, 293.66, 349.23), (207.65, 261.63, 311.13), (196.0, 246.94, 293.66), (207.65, 261.63, 311.13)],
        [(246.94, 311.13, 369.99), (220.0, 277.18, 329.63), (196.0, 246.94, 293.66), (220.0, 277.18, 329.63)],
    ]
    chords = progressions[int(rng.integers(0, len(progressions)))]
    semitone = int(rng.integers(-2, 3))
    trans = float(2 ** (semitone / 12.0))
    chords = [tuple(f * trans for f in triad) for triad in chords]

    bpm = int(rng.integers(96, 125))
    beat = 60.0 / bpm
    bar = beat * 4

    signal = np.zeros_like(t, dtype=np.float32)

    # Harmonic pad.
    bars = int(math.ceil(duration / bar))
    for i in range(bars):
        start = i * bar
        end = min(duration, start + bar)
        s_idx = int(start * sample_rate)
        e_idx = int(end * sample_rate)
        if e_idx <= s_idx:
            continue

        tt = t[s_idx:e_idx] - start
        chord = chords[i % len(chords)]

        pad = np.zeros_like(tt, dtype=np.float32)
        for f in chord:
            detune = float(rng.uniform(-1.5, 1.5))
            pad += np.sin(2 * np.pi * (f + detune) * tt)
        pad /= max(1.0, float(len(chord)))

        env = _envelope(len(tt), attack=0.15, release=0.35)
        signal[s_idx:e_idx] += 0.22 * pad * env

        # Pluck pulse each beat for rhythmic drive.
        for b in range(4):
            p_start = start + b * beat
            p_end = min(end, p_start + beat * 0.55)
            ps = int(p_start * sample_rate)
            pe = int(p_end * sample_rate)
            if pe <= ps:
                continue

            ptt = t[ps:pe] - p_start
            root = chord[0] * 2.0
            pluck = np.sin(2 * np.pi * root * ptt) * np.exp(-ptt * float(rng.uniform(5.5, 8.5)))
            signal[ps:pe] += float(rng.uniform(0.09, 0.15)) * pluck.astype(np.float32)

    # Gentle high shimmer.
    shimmer_freq = float(rng.uniform(760.0, 980.0))
    shimmer = 0.03 * np.sin(2 * np.pi * shimmer_freq * t) * (np.sin(2 * np.pi * 0.35 * t) * 0.5 + 0.5)
    signal += shimmer.astype(np.float32)

    # Limit + stereo spread.
    peak = float(np.max(np.abs(signal))) if signal.size else 1.0
    if peak > 0:
        signal = signal / peak
    signal *= 0.82

    right = np.roll(signal, int(0.0015 * sample_rate)) * 0.98
    stereo = np.stack([signal, right], axis=1)

    pcm = np.int16(np.clip(stereo, -1.0, 1.0) * 32767)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())

    return output_path


def mix_voice_and_music(
    *,
    voice_path: Path | None,
    music_path: Path,
    output_path: Path,
    target_duration: float,
    music_gain: float = 0.22,
    voice_gain: float = 1.0,
) -> Path:
    from moviepy.editor import AudioFileClip, CompositeAudioClip

    if not music_path.exists() or music_path.stat().st_size == 0:
        raise ValueError(f"Music track missing: {music_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    music_clip = AudioFileClip(str(music_path)).volumex(music_gain)

    clips = [music_clip.set_duration(max(1.0, target_duration))]
    voice_clip = None
    if voice_path and voice_path.exists() and voice_path.stat().st_size > 0:
        voice_clip = AudioFileClip(str(voice_path)).volumex(voice_gain)
        clips.append(voice_clip)

    mix = CompositeAudioClip(clips).set_duration(max(1.0, target_duration))
    mix.write_audiofile(str(output_path), fps=44100, nbytes=2, verbose=False, logger=None)

    try:
        mix.close()
    except Exception:
        pass
    try:
        music_clip.close()
    except Exception:
        pass
    if voice_clip is not None:
        try:
            voice_clip.close()
        except Exception:
            pass

    return output_path


