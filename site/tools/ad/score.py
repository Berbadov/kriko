"""Synthesises the advertisement's soundtrack: 120 beats per minute, in time with scenes.js.

    python site/tools/ad/score.py [out.wav]

Everything is made here from sine, saw and noise (numpy and scipy), so there is nothing to
license. The times below are the same times scenes.js lands things on: a cut, a slam, a
sticker, a ring. Change one file and change the other.
"""

import sys
import wave
from pathlib import Path

import numpy as np
from scipy import signal

SR = 44100
DURATION = 28.5
BEAT = 0.5
N = int(SR * DURATION)
rng = np.random.default_rng(7)


def t_of(n: int) -> np.ndarray:
    return np.arange(n) / SR


def place(bus: np.ndarray, at: float, sound: np.ndarray, gain: float = 1.0) -> None:
    i = int(at * SR)
    if i >= len(bus) or i < 0:
        return
    j = min(len(bus), i + len(sound))
    bus[i:j] += sound[: j - i] * gain


def env(n: int, decay: float, attack: float = 0.002) -> np.ndarray:
    t = t_of(n)
    return np.minimum(1.0, t / max(attack, 1e-4)) * np.exp(-t / decay)


def lp(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, hz, "low", fs=SR, output="sos"), x)


def hp(x: np.ndarray, hz: float, order: int = 2) -> np.ndarray:
    return signal.sosfilt(signal.butter(order, hz, "high", fs=SR, output="sos"), x)


def bp(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return signal.sosfilt(signal.butter(2, [lo, hi], "band", fs=SR, output="sos"), x)


def kick() -> np.ndarray:
    n = int(0.42 * SR)
    t = t_of(n)
    f = 46 + 130 * np.exp(-t / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.16)
    click = hp(rng.standard_normal(n), 2500) * env(n, 0.004) * 0.35
    return np.tanh(1.6 * (body + click))


def clap() -> np.ndarray:
    n = int(0.26 * SR)
    x = bp(rng.standard_normal(n), 900, 5200)
    burst = sum(np.roll(env(n, 0.012), int(k * 0.011 * SR)) for k in range(3))
    return x * (burst * 0.5 + env(n, 0.07) * 0.8)


def hat(open_: bool = False) -> np.ndarray:
    n = int((0.22 if open_ else 0.05) * SR)
    return hp(rng.standard_normal(n), 7000) * env(n, 0.09 if open_ else 0.012, 0.0005)


def thud() -> np.ndarray:
    n = int(0.22 * SR)
    t = t_of(n)
    f = 52 + 120 * np.exp(-t / 0.03)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.09)
    snap = bp(rng.standard_normal(n), 1200, 6000) * env(n, 0.012) * 0.5
    return np.tanh(1.4 * (body + snap))


def pop(pitch: float = 700.0) -> np.ndarray:
    n = int(0.16 * SR)
    t = t_of(n)
    f = pitch * (1 + 1.2 * np.exp(-t / 0.03))
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.05, 0.001) * 0.8


def blip(freq: float, length: float = 0.12) -> np.ndarray:
    n = int(length * SR)
    t = t_of(n)
    return (np.sin(2 * np.pi * freq * t) + 0.35 * np.sin(2 * np.pi * freq * 2 * t)) * env(n, length * 0.4, 0.001)


def chime(freq: float) -> np.ndarray:
    n = int(0.9 * SR)
    t = t_of(n)
    x = np.sin(2 * np.pi * freq * t) + 0.5 * np.sin(2 * np.pi * freq * 2.76 * t) * np.exp(-t / 0.12)
    return x * env(n, 0.28, 0.001)


def riser(length: float) -> np.ndarray:
    n = int(length * SR)
    t = t_of(n)
    sweep = signal.chirp(t, f0=180, f1=3200, t1=length, method="logarithmic")
    noise = hp(rng.standard_normal(n), 1800) * (t / length) ** 2
    shape = (t / length) ** 1.6
    return (sweep * 0.5 + noise * 0.9) * shape


def boom() -> np.ndarray:
    n = int(1.6 * SR)
    t = t_of(n)
    f = 38 + 90 * np.exp(-t / 0.2)
    sub = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.5, 0.001)
    crash = hp(rng.standard_normal(n), 3500) * env(n, 0.55, 0.001) * 0.5
    return np.tanh(1.3 * (sub + crash))


def saw(freq: float, n: int) -> np.ndarray:
    t = t_of(n)
    return 2 * ((t * freq) % 1.0) - 1


def pluck(freq: float, length: float = 0.22) -> np.ndarray:
    n = int(length * SR)
    t = t_of(n)
    x = 0.6 * saw(freq, n) + 0.4 * np.sign(np.sin(2 * np.pi * freq * t))
    return lp(x, 3600) * env(n, length * 0.45, 0.001)


def bass_note(freq: float, length: float) -> np.ndarray:
    n = int(length * SR)
    x = lp(saw(freq, n), 520, 3) + np.sin(2 * np.pi * freq * t_of(n)) * 0.7
    return x * env(n, length * 0.9, 0.003) * np.minimum(1.0, (n - np.arange(n)) / (0.01 * SR))


def pad(freqs, length: float) -> np.ndarray:
    n = int(length * SR)
    out = np.zeros(n)
    for f in freqs:
        for det in (-0.004, 0.0, 0.004):
            out += lp(saw(f * (1 + det), n), 1400)
    fade = np.minimum(1.0, np.arange(n) / (0.3 * SR)) * np.minimum(1.0, (n - np.arange(n)) / (0.6 * SR))
    return out * fade / (len(freqs) * 3)


def reverb(x: np.ndarray, wet: float = 0.25, seconds: float = 0.9) -> np.ndarray:
    n = int(seconds * SR)
    ir = rng.standard_normal(n) * np.exp(-np.arange(n) / (0.22 * SR))
    ir = lp(ir, 5000)
    return x * (1 - wet) + signal.fftconvolve(x, ir)[: len(x)] * wet * 0.06


# ── the song ──────────────────────────────────────────────────────────────────
drums = np.zeros(N)
bass = np.zeros(N)
lead = np.zeros(N)
pads = np.zeros(N)
fx = np.zeros(N)
kick_times: list[float] = []

K, C, H, HO = kick(), clap(), hat(), hat(True)

CUTS = [0.0, 2.0, 4.0, 6.0, 8.0, 12.0, 16.0, 19.0, 23.0]
# kick on every beat, thinner at the very start and gone for the last second
for b in np.arange(0, 27.0, BEAT):
    g = 0.55 if b < 2.0 else 0.9
    place(drums, b, K, g)
    kick_times.append(float(b))
# claps on 2 and 4, hats off the beat, open hats at the end of each bar
for b in np.arange(4.0, 23.0, BEAT):
    if int(round(b / BEAT)) % 2 == 1:
        place(drums, b, C, 0.45)
for b in np.arange(2.0, 26.0, BEAT):
    place(drums, b + BEAT / 2, H, 0.22)
    if 4.0 <= b < 6.0 or 16.0 <= b < 19.0:
        place(drums, b + BEAT / 4, H, 0.12)
        place(drums, b + BEAT * 0.75, H, 0.12)
    if int(round(b / BEAT)) % 4 == 3:
        place(drums, b + BEAT / 2, HO, 0.2)

# chords: Am F C G, one bar (two seconds) each, in A minor
CHORDS = [
    (55.0, [220.0, 261.63, 329.63]),
    (43.65, [174.61, 220.0, 261.63]),
    (65.41, [261.63, 329.63, 392.0]),
    (49.0, [196.0, 246.94, 293.66]),
]
for bar in range(0, 14):
    t0 = bar * 2.0
    if t0 < 2.0 or t0 >= 27.0:
        continue
    root, tones = CHORDS[bar % 4]
    # eighth-note bass with a rest on the last
    for e in range(8):
        if e == 7 and bar % 2:
            continue
        f = root * (2 if e in (3, 6) else 1)
        place(bass, t0 + e * BEAT / 2, bass_note(f, BEAT / 2 * 0.9), 0.5)
    if t0 >= 6.0:
        for s in range(16):
            tone = tones[[0, 1, 2, 1][s % 4]] * (2 if (bar >= 12 or 8.0 <= t0 < 12.0 and s % 8 >= 4) else 1)
            place(lead, t0 + s * BEAT / 4, pluck(tone), 0.16)
    if t0 >= 23.0 or 2.0 <= t0 < 4.0:
        place(pads, t0, pad(tones, 2.0 + (0.5 if t0 >= 26.0 else 0.0)), 0.55)

# the ends of things: a riser into every cut, a boom on it
for c in CUTS:
    if c > 0:
        length = 1.0 if c == 23.0 else 0.5
        place(fx, c - length, riser(length), 0.45 if c != 23.0 else 0.6)
    place(fx, c, boom(), 0.55 if c in (0.0, 4.0, 6.0, 23.0) else 0.4)

# things that land
THUDS = [0.45 + i * 0.045 for i in range(14)] if False else []
for tt in [2.0, 4.0, 4.25, 4.5, 5.0, 5.25, 5.5, 6.0, 6.5, 6.75, 7.0, 7.25, 8.0, 8.25, 9.0, 9.25, 10.5, 10.75,
           12.0, 12.25, 15.0, 16.0, 16.5, 17.0, 18.0, 23.0, 23.5, 23.75, 24.0, 24.25, 24.5, 24.75, 25.0]:
    place(fx, tt, thud(), 0.55)
# the caption typing itself
for i in range(14):
    place(fx, 0.45 + i * 0.045, blip(1500 + 60 * i, 0.04), 0.1)
# stickers, rings, the click
for tt, p in [(0.75, 500), (1.0, 620), (2.6, 760), (2.85, 860), (3.1, 960), (3.35, 1080),
              (11.1, 700), (11.5, 800), (13.7, 740), (14.6, 880), (25.5, 760), (25.75, 900), (26.25, 1040)]:
    place(fx, tt, pop(p), 0.6)
for tt, f in [(9.0, 1046.5), (9.5, 1174.7), (10.6, 1318.5), (10.9, 1396.9), (11.3, 1568.0),
              (13.5, 1046.5), (13.65, 1318.5), (14.55, 1174.7), (14.65, 1318.5), (14.75, 1568.0)]:
    place(fx, tt, blip(f, 0.14), 0.25)
place(fx, 10.1, blip(2200, 0.05), 0.4)
# the scan, the squiggle, the checks
place(fx, 2.2, riser(0.8), 0.4)
for tt in [19.15, 19.65, 20.15]:
    place(fx, tt, chime(1568.0), 0.3)
    place(fx, tt, chime(2093.0), 0.18)
# the tagline, climbing the scale as it is read
for i, f in enumerate([440.0, 493.9, 523.3, 587.3, 659.3, 783.99, 880.0]):
    place(lead, 23.5 + i * 0.25, pluck(f * 2, 0.4), 0.3)

# sidechain: the bass, pads and lead breathe out of every kick
t = t_of(N)
duck = np.ones(N)
for kt in kick_times:
    i = int(kt * SR)
    seg = min(N - i, int(0.35 * SR))
    duck[i : i + seg] = np.minimum(duck[i : i + seg], 1 - 0.75 * np.exp(-np.arange(seg) / (0.1 * SR)))
mix = drums * 0.9 + (bass * 0.8 + pads * 0.35 + lead * 0.9) * duck + reverb(lead + pads, 0.6) * 0.5 + fx
# a little glue and a clean start and end
mix = np.tanh(mix * 0.9)
mix *= np.minimum(1.0, t / 0.005) * np.minimum(1.0, (DURATION - t) / 0.7)
mix = mix / np.max(np.abs(mix)) * 0.66

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parent / "out" / "kriko-ad.wav")
out.parent.mkdir(parents=True, exist_ok=True)
with wave.open(str(out), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((mix * 32767).astype("<i2").tobytes())
print("wrote", out, f"{DURATION}s", "peak", round(float(np.max(np.abs(mix))), 3))
