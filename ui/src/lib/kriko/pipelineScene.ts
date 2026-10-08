/* The agent pipeline: the whole run on one stage, as a low-poly loop.
 *
 * Geometry, timing and the blue ramp follow `Motion.md` and the design
 * system's MotionLab, which is the reference for every number here. The
 * pattern is the lab's: a software projection of a few hundred flat faces,
 * sorted far to near, painted at 360 by 132 and scaled up with nearest
 * neighbour so each drawn pixel stays a square.
 *
 * This module has no DOM in it. It turns a moment into a list of draw
 * operations, so the geometry is testable without a canvas. The component
 * paints the list.
 */

export const SCENE_SECONDS = 10;
/** The stable frame drawn under reduced motion, as the lab draws it. */
export const REDUCED_FRAME_SECONDS = 8.9;
export const SCENE_WIDTH = 360;
export const SCENE_HEIGHT = 132;

/** The colours the scene paints with. Every one comes from the app's tokens. */
export interface Palette {
    deep: string;
    low: string;
    brand: string;
    hover: string;
    bright: string;
    ice: string;
    off: string;
}

export type Stage = "fetch" | "read" | "extract" | "write" | "done";

export type Point = [number, number];
type Vec = [number, number, number];

/** One thing to draw, already projected to the 2D canvas. */
export type Op =
    | { kind: "poly"; pts: Point[]; fill: string; stroke: string | null; z: number }
    | { kind: "seg"; a: Point; b: Point; c: string; z: number }
    | { kind: "dot"; x: number; y: number; size: number; c: string; z: number };

// Indices into the blue ramp, darkest to lightest, as the lab names them.
const DEEP = 0;
const LOW = 1;
const BRAND = 2;
const HOVER = 3;
const BRIGHT = 4;
const ICE = 5;

const CAPTIONS: Record<Stage, string> = {
    fetch: "fetch · GET site",
    read: "read · scanning the page for claims",
    extract: "extract · each claim keeps its source line",
    write: "write · inserting claims, evidence and source rows",
    done: "done · committed",
};

/** The stage a moment is in, and the caption the HUD shows for it. The
 * windows are the lab's, which overlap in the spec's table; these are the
 * ones the caption is read by. */
export function stageAt(t: number): { stage: Stage; caption: string } {
    const stage: Stage =
        t < 1.8 ? "fetch" : t < 4.2 ? "read" : t < 6.15 ? "extract" : t < 8.2 ? "write" : "done";
    return { stage, caption: CAPTIONS[stage] };
}

/** Read the palette from the app's tokens. `read` returns a token's value,
 * or an empty string where the token is not defined, which takes the fallback. */
export function paletteFrom(read: (token: string) => string): Palette {
    const pick = (token: string, fallback: string) => read(token) || fallback;
    return {
        deep: pick("brand-deep", "#0a1a66"),
        low: pick("brand-low", "#1739c2"),
        brand: pick("brand", "#1f4fff"),
        hover: pick("brand-hover", "#3a64ff"),
        bright: pick("brand-bright", "#86a3ff"),
        ice: pick("ice", "#bfe4ff"),
        off: pick("led-off", "#161d36"),
    };
}

// ── maths ───────────────────────────────────────────────────────────────

const cl = (x: number, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a: number, b: number, t: number) => a + (b - a) * t;
const pr = (t: number, a: number, b: number) => cl((t - a) / (b - a));
const eo = (x: number) => 1 - Math.pow(1 - x, 3);
const eio = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
const back = (x: number) => {
    const c1 = 1.70158;
    const c3 = c1 + 1;
    return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2);
};
const sub = (a: Vec, b: Vec): Vec => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const cross = (a: Vec, b: Vec): Vec => [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
];
const dot3 = (a: Vec, b: Vec) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const unit = (v: Vec): Vec => {
    const n = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / n, v[1] / n, v[2] / n];
};
const LIGHT = unit([-0.45, 0.75, -0.5]);

/** Rotate about x, then y, then z, as the lab does. */
function rot(p: Vec, ax: number, ay: number, az: number): Vec {
    let [x, y, z] = p;
    let c = Math.cos(az);
    let s = Math.sin(az);
    [x, y] = [x * c - y * s, x * s + y * c];
    c = Math.cos(ax);
    s = Math.sin(ax);
    [y, z] = [y * c - z * s, y * s + z * c];
    c = Math.cos(ay);
    s = Math.sin(ay);
    [x, z] = [x * c + z * s, -x * s + z * c];
    return [x, y, z];
}

// ── the stage ───────────────────────────────────────────────────────────

const FOCAL = 300;
const GLOBE: Vec = [-7.4, 0.6, 0];
const DB: Vec = [6.6, -0.2, 0];
const PAGE_SPOT: Vec = [-2.3, 0.35, 0];
const RAIL = -2.35;
/** The page's text lines: height, width, and whether the line is a claim. */
const LINES = [1.55, 0.95, 0.4, -0.15, -0.7, -1.25, -1.7].map((y, i) => ({
    y,
    w: [2.3, 1.8, 2.5, 1.4, 2.2, 1.9, 1.2][i],
    claim: [1, 2, 4, 5].includes(i),
}));
const BOX_CORNERS: Vec[] = [
    [-1, -1, -1],
    [1, -1, -1],
    [1, 1, -1],
    [-1, 1, -1],
    [-1, -1, 1],
    [1, -1, 1],
    [1, 1, 1],
    [-1, 1, 1],
];
const BOX_FACES = [
    [0, 1, 2, 3],
    [5, 4, 7, 6],
    [4, 0, 3, 7],
    [1, 5, 6, 2],
    [3, 2, 6, 7],
    [4, 5, 1, 0],
];

interface Cam {
    yaw: number;
    pitch: number;
    dist: number;
    tx: number;
    ty: number;
}
interface Pose {
    pos: Vec;
    s: number;
    ry: number;
    rz: number;
}
interface PolyOpts {
    fill?: string;
    stroke?: string | null;
    bias?: number;
    boost?: number;
    center?: Vec;
}

/** One frame being drawn: the camera, the palette and the ops so far. */
class Drawing {
    readonly ops: Op[] = [];
    private readonly cam: Cam;
    private readonly ramp: string[];

    constructor(cam: Cam, palette: Palette) {
        this.cam = cam;
        this.ramp = [
            palette.deep,
            palette.low,
            palette.brand,
            palette.hover,
            palette.bright,
            palette.ice,
        ];
    }

    private get ice() {
        return this.ramp[ICE];
    }

    private view(p: Vec): Vec {
        const { cam } = this;
        let x = p[0] - cam.tx;
        let y = p[1] - cam.ty;
        let z = p[2];
        let c = Math.cos(cam.yaw);
        let s = Math.sin(cam.yaw);
        [x, z] = [x * c + z * s, -x * s + z * c];
        c = Math.cos(cam.pitch);
        s = Math.sin(cam.pitch);
        [y, z] = [y * c + z * s, -y * s + z * c];
        return [x, y, z + cam.dist];
    }

    private project(v: Vec): Point {
        const f = FOCAL / v[2];
        return [SCENE_WIDTH / 2 + v[0] * f, SCENE_HEIGHT / 2 - v[1] * f];
    }

    /** A flat face, lit by the light and culled when it faces away. */
    poly(points: Vec[], o: PolyOpts = {}) {
        const v = points.map((p) => this.view(p));
        if (v.some((a) => a[2] < 2)) return;
        let n = unit(cross(sub(v[1], v[0]), sub(v[2], v[0])));
        if (o.center) {
            const c = this.view(o.center);
            if (dot3(n, sub(v[0], c)) < 0) n = [-n[0], -n[1], -n[2]];
            if (dot3(n, v[0]) > 0) return;
        } else if (dot3(n, v[0]) > 0) {
            n = [-n[0], -n[1], -n[2]];
        }
        const lv = cl(Math.floor(cl(dot3(n, LIGHT) * 0.5 + 0.5) * 5.99) + (o.boost ?? 0), 0, 5);
        const z = v.reduce((sum, a) => sum + a[2], 0) / v.length - (o.bias ?? 0);
        this.ops.push({
            kind: "poly",
            pts: v.map((a) => this.project(a)),
            z,
            fill: o.fill ?? this.ramp[lv],
            stroke: o.stroke === undefined ? this.ice : o.stroke,
        });
    }

    seg(a: Vec, b: Vec, c: string, bias = 0) {
        const va = this.view(a);
        const vb = this.view(b);
        if (va[2] < 2 || vb[2] < 2) return;
        this.ops.push({
            kind: "seg",
            a: this.project(va),
            b: this.project(vb),
            c,
            z: (va[2] + vb[2]) / 2 - bias,
        });
    }

    dot(p: Vec, c: string, size = 2, bias = 0) {
        const v = this.view(p);
        if (v[2] < 2) return;
        const [x, y] = this.project(v);
        this.ops.push({ kind: "dot", x, y, size, c, z: v[2] - bias });
    }

    box(c: Vec, s: number, r: Vec, o: PolyOpts = {}) {
        const corners = BOX_CORNERS.map((p) => {
            const q = rot([p[0] * s * 0.5, p[1] * s * 0.5, p[2] * s * 0.5], ...r);
            return [q[0] + c[0], q[1] + c[1], q[2] + c[2]] as Vec;
        });
        for (const face of BOX_FACES) this.poly(face.map((i) => corners[i]), { ...o, center: c });
    }

    cyl(c: Vec, r: number, h: number, n: number, o: PolyOpts = {}) {
        const top: Vec[] = [];
        const bot: Vec[] = [];
        for (let i = 0; i < n; i++) {
            const a = (i / n) * Math.PI * 2;
            top.push([c[0] + Math.cos(a) * r, c[1] + h / 2, c[2] + Math.sin(a) * r]);
            bot.push([c[0] + Math.cos(a) * r, c[1] - h / 2, c[2] + Math.sin(a) * r]);
        }
        for (let i = 0; i < n; i++) {
            const j = (i + 1) % n;
            this.poly([bot[i], bot[j], top[j], top[i]], { ...o, center: c });
        }
        this.poly(top, { ...o, center: c, boost: (o.boost ?? 0) + 1 });
    }

    /** The page being carried: a card, with a beam down it and its text lines. */
    page(pose: Pose, beamY: number | null, lit: boolean[]) {
        const [px, py, pz] = pose.pos;
        const s = pose.s;
        const at = (p: readonly number[]): Vec => {
            const q = rot([p[0] * s, p[1] * s, p[2] * s], 0, pose.ry, pose.rz);
            return [q[0] + px, q[1] + py, q[2] + pz];
        };
        this.poly(
            [
                [-1.6, -2.1, 0],
                [1.6, -2.1, 0],
                [1.6, 2.1, 0],
                [-1.6, 2.1, 0],
            ].map(at),
            { fill: this.ramp[BRAND], stroke: this.ice, bias: 0 },
        );
        if (beamY !== null) {
            this.poly(
                [
                    [-1.6, beamY, -0.03],
                    [1.6, beamY, -0.03],
                    [1.6, 2.1, -0.03],
                    [-1.6, 2.1, -0.03],
                ].map(at),
                { fill: this.ramp[HOVER], stroke: null, bias: 0.02 },
            );
            // The lab draws this line white. The design system allows the blue
            // ramp only, so the brightest step stands in for it.
            this.poly(
                [
                    [-1.9, beamY - 0.05, -0.08],
                    [1.9, beamY - 0.05, -0.08],
                    [1.9, beamY + 0.05, -0.08],
                    [-1.9, beamY + 0.05, -0.08],
                ].map(at),
                { fill: this.ice, stroke: null, bias: 0.06 },
            );
        }
        LINES.forEach((line, i) => {
            const x0 = -1.3;
            const x1 = x0 + line.w;
            const fill = lit[i] ? (line.claim ? this.ice : this.ramp[BRIGHT]) : this.ramp[LOW];
            this.poly(
                [
                    [x0, line.y - 0.1, -0.05],
                    [x1, line.y - 0.1, -0.05],
                    [x1, line.y + 0.1, -0.05],
                    [x0, line.y + 0.1, -0.05],
                ].map(at),
                { fill, stroke: null, bias: 0.04 },
            );
        });
    }

    /** The globe that fetches: latitude rings, meridians and a few lit dots. */
    globe(t: number, radius = 1.9, gc: Vec = GLOBE) {
        const spin = t * 0.9;
        const ring = (lat: number) => {
            const r = Math.cos(lat) * radius;
            const y = Math.sin(lat) * radius;
            let prev: Vec | null = null;
            for (let i = 0; i <= 22; i++) {
                const a = (i / 22) * Math.PI * 2 + spin;
                const p: Vec = [gc[0] + Math.cos(a) * r, gc[1] + y, gc[2] + Math.sin(a) * r];
                if (prev) this.seg(prev, p, (p[2] + prev[2]) / 2 < gc[2] ? this.ramp[BRIGHT] : this.ramp[LOW]);
                prev = p;
            }
        };
        [-1, -0.5, 0, 0.5, 1].forEach((k) => ring(k * 1.05));
        for (let m = 0; m < 6; m++) {
            const lo = (m / 6) * Math.PI * 2 + spin;
            let prev: Vec | null = null;
            for (let i = 0; i <= 18; i++) {
                const la = -Math.PI / 2 + (i / 18) * Math.PI;
                const p: Vec = [
                    gc[0] + Math.cos(la) * Math.cos(lo) * radius,
                    gc[1] + Math.sin(la) * radius,
                    gc[2] + Math.cos(la) * Math.sin(lo) * radius,
                ];
                if (prev) this.seg(prev, p, (p[2] + prev[2]) / 2 < gc[2] ? this.ramp[BRIGHT] : this.ramp[LOW]);
                prev = p;
            }
        }
        for (const [la, lo] of [
            [0.3, 0.4],
            [-0.2, 1.9],
            [0.6, 3.2],
            [0.1, 4.5],
            [-0.5, 5.4],
        ]) {
            const a = lo + spin;
            const p: Vec = [
                gc[0] + Math.cos(la) * Math.cos(a) * radius,
                gc[1] + Math.sin(la) * radius,
                gc[2] + Math.cos(la) * Math.sin(a) * radius,
            ];
            if (p[2] < gc[2] + 0.2) this.dot(p, this.ice, 3, 0.3);
        }
    }

    floor() {
        const y = -2.5;
        for (let z = -4; z <= 4; z += 2) this.seg([-10.5, y, z], [9.5, y, z], this.ramp[DEEP], -5);
        for (let x = -10; x <= 9.5; x += 2.5) this.seg([x, y, -4], [x, y, 4], this.ramp[DEEP], -5);
    }

    /** The three-disc SQLite cylinder, with a slot per claim that has landed. */
    database(landed: number, flash: number, off: string) {
        const base = -1.45;
        const hh = 0.95;
        const gap = 0.18;
        const r = 1.55;
        for (let i = 0; i < 3; i++) {
            this.cyl([DB[0], base + i * (hh + gap), DB[2]], r, hh, 16, {
                boost: i === 2 ? Math.round(flash * 3) : 0,
            });
        }
        for (let k = 0; k < 4; k++) {
            const x = DB[0] - 1.05 + k * 0.7;
            const y = base + hh + gap;
            const fill = k < landed ? this.ice : off;
            this.poly(
                [
                    [x - 0.2, y - 0.2, -r + 0.08],
                    [x + 0.2, y - 0.2, -r + 0.08],
                    [x + 0.2, y + 0.2, -r + 0.08],
                    [x - 0.2, y + 0.2, -r + 0.08],
                ],
                { fill, stroke: null, bias: 0.3 },
            );
        }
    }
}

/** Everything drawn for one moment of the loop, far to near. The clock wraps
 * every ten seconds, so the frame at `SCENE_SECONDS` is the frame at zero.
 * `reduced` draws the scene still, as the lab does under reduced motion: no
 * sway and no spin. */
export function sceneOps(clock: number, reduced: boolean, palette: Palette): Op[] {
    const t = ((clock % SCENE_SECONDS) + SCENE_SECONDS) % SCENE_SECONDS;
    const cam: Cam = {
        yaw: reduced ? 0 : Math.sin(t * 0.4) * 0.16,
        pitch: 0.2,
        dist: 19,
        tx: 0,
        ty: 0.2,
    };
    const d = new Drawing(cam, palette);

    d.floor();
    for (let x = -6.3; x < 5; x += 0.8) d.seg([x, RAIL, 0], [x + 0.35, RAIL, 0], palette.low);
    d.globe(reduced ? 0 : t);

    // The request ring that pulses on the globe at each fetch.
    const rp = pr(t, 0, 1.4);
    if (rp > 0 && rp < 1) {
        const r = 1.9 + rp * 2.2;
        let prev: Vec | null = null;
        for (let i = 0; i <= 24; i++) {
            const a = (i / 24) * Math.PI * 2;
            const p: Vec = [GLOBE[0] + Math.cos(a) * r, GLOBE[1] + Math.sin(a) * r, 0];
            if (prev) d.seg(prev, p, rp < 0.7 ? palette.bright : palette.low, -1);
            prev = p;
        }
    }

    // The page: it flies from the globe to the reading spot, is scanned, then exits.
    let pose: Pose | null = null;
    const pa = pr(t, 0, 1.8);
    if (t < 6.7) {
        const p = eo(pa);
        const pos: Vec = [
            lerp(GLOBE[0] + 1.6, PAGE_SPOT[0], p),
            lerp(GLOBE[1], PAGE_SPOT[1], p) + Math.sin(Math.PI * p) * 2.4 + (t > 1.8 ? Math.sin(t * 1.8) * 0.06 : 0),
            0,
        ];
        const sc = t < 6.0 ? lerp(0.25, 1, eo(pa)) : lerp(1, 0, eio(pr(t, 6.0, 6.7)));
        pose = { pos, s: Math.max(sc, 0.01), ry: lerp(1.45, -0.12, p), rz: Math.sin(p * Math.PI) * 0.35 };
    }

    // The scan line: it travels down the page, lighting the text it passes.
    const bp = pr(t, 1.8, 4.2);
    let beamY: number | null = null;
    const lit = LINES.map(() => false);
    if (t >= 1.8 && t <= 6.0) {
        const by = bp < 1 ? lerp(2.1, -2.1, eio(bp)) : -9;
        beamY = by;
        LINES.forEach((line, i) => {
            lit[i] = by === -9 || line.y > by;
        });
    }
    if (pose) d.page(pose, beamY === -9 ? null : beamY, lit);

    // The four claims: each lifts off the page, hops to the cylinder and lands.
    let landed = 0;
    let flash = 0;
    for (let k = 0; k < 4; k++) {
        const spawn = 4.1 + 0.4 * k;
        const hop = 4.95 + 0.42 * k;
        const arrive = 6.15 + 0.42 * k;
        const land = arrive + 0.3;
        if (t < spawn) continue;
        if (t >= land) {
            landed++;
            if (t < land + 0.35) flash = Math.max(flash, 1 - (t - land) / 0.35);
            continue;
        }
        const line = LINES[[1, 2, 4, 5][k]];
        const start: Vec = [PAGE_SPOT[0] - 1.3 + line.w / 2, PAGE_SPOT[1] + line.y, -0.2];
        const slot: Vec = [DB[0], 2.5, 0];
        const pop = back(pr(t, spawn, spawn + 0.28));
        let sc = Math.max(pop, 0) * 0.55;
        let pos: Vec;
        let r: Vec;
        if (t < hop) {
            pos = [start[0], start[1] + Math.sin(t * 3 + k) * 0.04, start[2]];
            r = [0, t * 0.5, 0];
            sc *= 0.8;
        } else {
            const e = eio(pr(t, hop, arrive));
            pos = [
                lerp(start[0], slot[0], e),
                lerp(start[1], slot[1], e) + Math.sin(Math.PI * e) * 1.7,
                lerp(start[2], slot[2], e),
            ];
            r = [e * 5, e * 6 + k, e * 3];
            if (t >= arrive) {
                const u2 = pr(t, arrive, land);
                pos = [slot[0], lerp(slot[1], -0.1, eo(u2)), 0];
                r = [0, t * 1.2, 0];
                sc *= lerp(1, 0.45, u2);
            }
        }
        d.box(pos, Math.max(sc, 0.01), r, { stroke: palette.ice });
    }
    d.database(landed, flash, palette.off);

    return d.ops.sort((a, b) => b.z - a.z);
}
