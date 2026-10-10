"""Bakes the KRIKO leaf-shadow sky as a loopable PNG frame strip for GPUI.

Same recipe as the sky in MotionLab: fBm clouds, two layers of leaf shadows
swaying on two branch lines, 8x8 Bayer dither over the blue ramp.
GPUI cannot dither live at a cheap cost, so bake the frames and cycle them
with `with_animation` (stepped, 8 fps). Needs numpy and Pillow.

    python3 shimmer.py            # calm,   128 frames -> sky-calm/00.png ...
    python3 shimmer.py breezy     # breezy,  85 frames -> sky-breezy/00.png ...

Loop length is 16 s / speed. Far leaves sway at half the base rate, near
leaves at the base rate, so every harmonic closes on the same frame.
"""
import sys, os
import numpy as np
from PIL import Image

W, H, SCALE, FPS, SEED = 300, 76, 4, 8, 7
PAL = np.array([(0x05,0x07,0x0f),(0x0a,0x1a,0x66),(0x17,0x39,0xc2),(0x1f,0x4f,0xff),(0x3a,0x64,0xff),(0x86,0xa3,0xff),(0xbf,0xe4,0xff)], dtype=np.uint8)  # ground, brand-deep, brand-low, brand, brand-hover, brand-bright, ice

def bayer8():
    m = np.array([[0, 2], [3, 1]])
    for _ in range(2):
        n = m.shape[0]
        m = np.block([[4*m, 4*m+2], [4*m+3, 4*m+1]])
    return (m + .5) / 64

def mulberry(a):
    a &= 0xFFFFFFFF
    def nxt():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((a ^ (a >> 15)) * (1 | a)) & 0xFFFFFFFF
        t = (t + (((t ^ (t >> 7)) * (61 | t)) & 0xFFFFFFFF)) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return nxt

def hs(x, y, seed):
    h = (x.astype(np.int64) * 374761393 + y.astype(np.int64) * 668265263 + seed * 1442695041) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFFFFFF) / 4294967296

def vnoise(x, y, seed):
    xi, yi = np.floor(x), np.floor(y); fx, fy = x - xi, y - yi
    u, v = fx*fx*(3-2*fx), fy*fy*(3-2*fy)
    a, b = hs(xi, yi, seed), hs(xi+1, yi, seed)
    c, d = hs(xi, yi+1, seed), hs(xi+1, yi+1, seed)
    return (a*(1-u) + b*u)*(1-v) + (c*(1-u) + d*u)*v

def smooth(a, b, x):
    t = np.clip((x-a)/(b-a), 0, 1); return t*t*(3-2*t)

def make(seed=SEED):
    yy, xx = np.mgrid[0:H, 0:W].astype(float)
    S = H / 76
    f, amp, fr = 0, .5, 1/(30*S)
    for _ in range(4):
        f = f + amp*vnoise(xx*fr, yy*fr, seed); fr *= 2; amp *= .5
    nx, ny = xx/W, yy/H
    base = 2.9 + .9*(1-ny) + np.clip((f-.5)*5, 0, 1)*(.3 + 1.1*nx)*2
    base *= 1 - smooth(.8, 1, ny)
    rnd = mulberry(seed)
    br = [(W*1.05, -H*.1, W*.1, H*.85), (W*.8, H*1.0, W*.45, -H*.1)]
    leaves = []
    for layer in range(2):
        for i in range(14 if layer else 11):
            b = br[i % 2]; u, off = rnd(), (rnd()-.5)*28*S
            dx, dy = b[2]-b[0], b[3]-b[1]; l = np.hypot(dx, dy)
            a = (9 if layer else 15 + rnd()*7) * S * (.8 + rnd()*.5)
            leaves.append(dict(x=b[0]+dx*u-dy/l*off, y=b[1]+dy*u+dx/l*off, a=a, b=a*.36,
                th0=rnd()*np.pi, ph=rnd()*6.28, ax=(5 if layer else 3)*S, ay=(3.5 if layer else 2)*S,
                depth=1.4 if layer else .9, sp=1 if layer else .5))
    return base, leaves, br, xx, yy, bayer8()

def frame(state, t, wind=1.0):
    base, leaves, br, xx, yy, B = state
    sh = np.zeros((H, W))
    ph = t / 8 * 2*np.pi * (1.5 if wind > 1 else 1)
    for l in leaves:
        ox = (np.sin(ph*l['sp']+l['ph']) + .35*np.sin(ph*2*l['sp']+l['ph']*1.7)) * l['ax'] * wind
        oy = np.cos(ph*l['sp']+l['ph']*1.3) * l['ay'] * wind
        th = l['th0'] + np.sin(ph*l['sp']+l['ph']*.7) * .45 * wind
        c, s = np.cos(th), np.sin(th)
        dx, dy = xx-(l['x']+ox), yy-(l['y']+oy)
        u, v = dx*c + dy*s, -dx*s + dy*c; sn = u / l['a']
        ok = np.abs(sn) <= 1
        cov = l['b']*np.power(np.clip(1-sn*sn, 0, 1), .7) - np.abs(v)
        val = np.where(ok & (cov > 0), np.minimum(1, cov/1.1)*l['depth'], 0)
        sh = np.maximum(sh, val)
    for k, b in enumerate(br):
        sw = np.sin(ph*.5 + k*2) * 3 * wind
        u = np.linspace(0, 1, 121)
        x = np.round(b[0]+(b[2]-b[0])*u+sw).astype(int); y = np.round(b[1]+(b[3]-b[1])*u+sw*.6).astype(int)
        m = (x >= 0) & (x < W) & (y >= 0) & (y < H)
        sh[y[m], x[m]] = np.maximum(sh[y[m], x[m]], 1.3)
    bay = np.tile(B, (H//8 + 1, W//8 + 1))[:H, :W]
    lv = np.clip(np.floor(base - sh + bay), 0, 6).astype(int)
    img = Image.fromarray(PAL[lv])
    return img.resize((W*SCALE, H*SCALE), Image.NEAREST)

if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'calm'
    wind = 2.0 if mode == 'breezy' else 1.0
    speed = 1.5 if wind > 1 else 1.0
    n = round(16 / speed * FPS)
    out = f'sky-{mode}'; os.makedirs(out, exist_ok=True)
    st = make()
    for i in range(n):
        frame(st, i / FPS, wind).save(f'{out}/{i:02d}.png', optimize=True)
    print(n, 'frames ->', out)
