#!/usr/bin/env python3
"""Build the ultrawide IPS32 patches for Ocarina of Time (Switch 2), main build E0F3CCFA...

The game builds each sead::PerspectiveProjection matrix in sead's doUpdateMatrix or in one of
three inlined copies of it. At every one of those sites an aspect within 0.01 of 16:9 is replaced
by the target aspect (and written back to mAspect). The w/h aspect the renderer hands to shaders
gets the same mapping. 1:1, 4:3 etc. views are untouched.

The picture the game renders (2560x1440, scene 1920x1080) takes the screen's shape: 3440x1440,
2560x1080, 3416x1440 (for 5120x2160) or 4096x1152 (32:9; 5120x1440 ran out of the game's render-target
memory and crashed), or 2304x1440 (16:10).
Full-screen 2D (the 3840x2160 layout ortho, spread over the whole picture) is squeezed horizontally
by (16/9)/target (vertically by target/(16/9) on a 16:10 screen), so the HUD sits undistorted in a
centred 16:9 area. Pre-rendered movies get the same centred 16:9 viewport.

  python3 build.py                         # writes releases/<zip>.zip, each holding
                                           #   0400486024DEC000/<mod name>/exefs/<id>.ips
  python3 build.py --verify-main main.bin  # also checks original words in a raw main image dump
"""
from pathlib import Path
import argparse
import struct
import zipfile

TITLE_ID = "0400486024DEC000"
BUILD_ID = "E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348"
VARIANTS = {  # mod folder name -> (zip file name, target display aspect, picture width, height)
    "Ultrawide 21x9 (3440x1440)": ("oot-ultrawide-21x9-3440x1440.zip", 3440 / 1440, 3440, 1440),
    "Ultrawide 21x9 (2560x1080)": ("oot-ultrawide-21x9-2560x1080.zip", 2560 / 1080, 2560, 1080),
    # 64:27 at the game's own height (whole multiples of 8), so the emulator's upscale to 5120x2160 stays sharp
    "Ultrawide 21x9 (5120x2160)": ("oot-ultrawide-21x9-5120x2160.zip", 5120 / 2160, 3416, 1440),
    "Super Ultrawide 32x9": ("oot-super-ultrawide-32x9.zip", 32 / 9, 4096, 1152),  # 5120x1440 crashed: out of render-target memory
    "Widescreen 16x10": ("oot-16x10.zip", 16 / 10, 2304, 1440),  # Steam Deck: the game's height, fewer pixels than stock
}
NSO_HEADER_SIZE = 0x100
CAVE_BASE = 0x3C46800  # zero executable padding after .text, up to 0x3C47000. Lichii's built-in
# patches now use 0x3C46200..0x3C46494 (Dynamic FPS / FPS Unlock, texture pool, water steps,
# photo mode); at 0x3C46400 the mod made Lichii skip Dynamic FPS, FPS Unlock and Photo Mode.


def f32(x): return struct.unpack("<I", struct.pack("<f", x))[0]


ASPECT_16_9, EPSILON = f32(16 / 9), f32(0.01)
UI_M00, UI_M11 = f32(2 / 3840), f32(2 / 2160)  # full-screen 2D layout ortho
SCREEN_CANVAS = 0x1B8  # offset of the 2D canvas inside every UI screen object
# UI screens (by vptr) that must cover the whole frame (full-frame captures, fades); they stay unsqueezed
FULL_FRAME_SCREENS = (
    0x4BED098,  # UIShortCutBGScreen: L/R item menu background (ShortCutBG_00)
    0x4BE4FB0,  # pause and system menu backgrounds (MenuBG_00, SystemBG_00)
    0x4BE7B30,  # area loading fade (LoadingFade_00)
    0x4BE61C8,  # cutscene fades (EventFade_00, EventSkipFade_00)
)


# Minimal A64 encoders for the instructions used below.
def movz(rd, imm): return 0x52800000 | imm << 5 | rd
def movz_x(rd, imm): return 0xD2800000 | imm << 5 | rd
def movk_x32(rd, imm): return 0xF2C00000 | imm << 5 | rd       # movk xd, #imm, lsl #32
def movk16(rd, imm): return 0x72A00000 | imm << 5 | rd
def fmov_sw(sd, wn): return 0x1E270000 | wn << 5 | sd
def fsub(sd, sn, sm): return 0x1E203800 | sm << 16 | sn << 5 | sd
def fabs_(sd, sn): return 0x1E20C000 | sn << 5 | sd
def fcmp(sn, sm): return 0x1E202000 | sm << 16 | sn << 5
def b_pl(words): return 0x54000005 | (words & 0x7FFFF) << 5
def str_s(st, xn, imm): return 0xBD000000 | (imm // 4) << 10 | xn << 5 | st
def ldp_s(s1, s2, xn, imm): return 0x2D400000 | ((imm // 4) & 0x7F) << 15 | s2 << 10 | xn << 5 | s1
def scvtf_sw(sd, wn): return 0x1E220000 | wn << 5 | sd
def fdiv(sd, sn, sm): return 0x1E201800 | sm << 16 | sn << 5 | sd
def ldp_q(q1, q2, xn, imm): return 0xAD400000 | ((imm // 16) & 0x7F) << 15 | q2 << 10 | xn << 5 | q1
def fmov_ws(wd, sn): return 0x1E260000 | sn << 5 | wd
def cmp_w(wn, wm): return 0x6B00001F | wm << 16 | wn << 5
def b_ne(words): return 0x54000001 | (words & 0x7FFFF) << 5
def umov_s1(wd, vn): return 0x0E0C3C00 | vn << 5 | wd           # mov wd, vn.s[1]
def and_abs(wd, wn): return 0x12007800 | wn << 5 | wd           # and wd, wn, #0x7fffffff
def dup_4s(vd, wn): return 0x4E040C00 | wn << 5 | vd
def fmul_4s(vd, vn, vm): return 0x6E20DC00 | vm << 16 | vn << 5 | vd
def sub_x(xd, xn, imm): return 0xD1000000 | imm << 10 | xn << 5 | xd
def ldr_s(st, xn, imm): return 0xBD400000 | (imm // 4) << 10 | xn << 5 | st
def fadd(sd, sn, sm): return 0x1E202800 | sm << 16 | sn << 5 | sd
def fmul(sd, sn, sm): return 0x1E200800 | sm << 16 | sn << 5 | sd
def ldp_x(x1, x2, xn, imm): return 0xA9400000 | ((imm // 8) & 0x7F) << 15 | x2 << 10 | xn << 5 | x1
def ldr_x(xt, xn): return 0xF9400000 | xn << 5 | xt
def add_x(xd, xn, imm): return 0x91000000 | imm << 10 | xn << 5 | xd
def cmp_x(xn, xm): return 0xEB00001F | xm << 16 | xn << 5
def b_eq(words): return 0x54000000 | (words & 0x7FFFF) << 5
def lsl_x(xd, xn, sh): return 0xD3400000 | (-sh % 64) << 16 | (63 - sh) << 10 | xn << 5 | xd


def adrp_add(xd, target):
    """PC-relative address of a module offset; returns words that need their own pc (resolved in edits())."""
    def adrp(pc):
        pages = (target >> 12) - (pc >> 12)
        return 0x90000000 | (pages & 3) << 29 | ((pages >> 2) & 0x7FFFF) << 5 | xd
    return [adrp, add_x(xd, xd, target & 0xFFF)]


def branch(frm, to):
    delta = to - frm
    assert delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27), "branch out of range"
    return 0x14000000 | ((delta // 4) & 0x3FFFFFF)


def load_f32(wt, st, bits):
    return [movz(wt, bits & 0xFFFF), movk16(wt, bits >> 16), fmov_sw(st, wt)]


def fix_aspect(target, sa, wt, sp, sq, writeback=None):
    """if |sa - 16/9| < 0.01: sa = target (and store it to [writeback, #176]). b.pl leaves NaN alone."""
    tail = load_f32(wt, sa, target) + ([str_s(sa, writeback, 176)] if writeback is not None else [])
    return (load_f32(wt, sp, ASPECT_16_9) + [fsub(sp, sa, sp), fabs_(sp, sp)] + load_f32(wt, sq, EPSILON)
            + [fcmp(sp, sq), b_pl(len(tail) + 1)] + tail)


def squash_ui(row, squash):
    """2D canvas matrix setup, after ldp q1, q4, [x2] (x2 = row-major projection, x0 = canvas; q1 = row 0,
    q4 = row 1): if it is the full-screen 3840x2160 ortho, scale that row so the HUD fills the centre 16:9
    of the frame. FULL_FRAME_SCREENS are skipped: they must keep covering the whole frame."""
    tail = [movz(16, squash & 0xFFFF), movk16(16, squash >> 16), dup_4s(17, 16), fmul_4s(row, row, 17)]
    # every full-screen layout canvas is embedded in a UI screen at +0x1b8: compare that screen's vptr
    check_bg = [sub_x(17, 0, SCREEN_CANVAS), ldr_x(16, 17)]
    for i, vtable in enumerate(FULL_FRAME_SCREENS):
        later = 4 * (len(FULL_FRAME_SCREENS) - 1 - i)  # adrp, add, cmp, b.eq per remaining screen
        check_bg += adrp_add(17, vtable) + [cmp_x(16, 17), b_eq(later + len(tail) + 1)]
    check_m11 = [umov_s1(16, 4), and_abs(16, 16), movz(17, UI_M11 & 0xFFFF), movk16(17, UI_M11 >> 16),
                 cmp_w(16, 17), b_ne(len(check_bg) + len(tail) + 1)]
    return ([ldp_q(1, 4, 2, 0), fmov_ws(16, 1), movz(17, UI_M00 & 0xFFFF), movk16(17, UI_M00 >> 16),
             cmp_w(16, 17), b_ne(len(check_m11) + len(check_bg) + len(tail) + 1)] + check_m11 + check_bg + tail)


def box_movie(margin, lo):
    """Movie layer draw, right after its full-render-target viewport (sead::Viewport at x29-40: minX +8,
    minY +12, maxX +16, maxY +20) is built: shrink it to the centre 16:9 of the frame, along x (lo = 8)
    or y (lo = 12)."""
    hi = lo + 8
    return [sub_x(16, 29, 40), ldr_s(16, 16, lo), ldr_s(17, 16, hi), fsub(18, 17, 16),
            movz(17, margin & 0xFFFF), movk16(17, margin >> 16), fmov_sw(19, 17),
            fmul(18, 18, 19), fadd(16, 16, 18), fsub(17, 17, 18), str_s(16, 16, lo), str_s(17, 16, hi),
            ldp_x(9, 8, 19, 24)]


def hooks(aspect):
    """(hook offset, original word, cave body, return address) for a target display aspect.
    Scratch registers are ones the original code overwrites right after the hook (or w16/w17/v16-v19)."""
    target, squash = f32(aspect), (16 / 9) / aspect
    # the HUD keeps its 16:9 shape: squeezed into the centre of a wider screen's width (canvas row 0,
    # viewport x, speech bubble x = ndc x * 1920), or of a taller (16:10) screen's height (row 1, y, ndc y * 1080)
    if squash <= 1:
        row, viewport_lo, (anchor, anchor_word, half) = 1, 8, (0x020C2B0, 0x52A89E08, 1920)
    else:
        squash, row, viewport_lo, (anchor, anchor_word, half) = 1 / squash, 4, 12, (0x020C2B8, 0x52A890E8, 1080)
    return [
        # sead::PerspectiveProjection::doUpdateMatrix: ldp s0, s1, [x0, #172]
        (0x3485CC0, 0x2D558400, [ldp_s(0, 1, 0, 172)] + fix_aspect(target, 1, 16, 16, 17, writeback=0), 0x3485CC4),
        # inlined copies: ldp s0, s3, [x21|x0, #172] / ldp s0, s1, [x2, #172]
        (0x004F1E8, 0x2D558EA0, [ldp_s(0, 3, 21, 172)] + fix_aspect(target, 3, 9, 4, 5, writeback=21), 0x004F1EC),
        (0x023B9A8, 0x2D558C00, [ldp_s(0, 3, 0, 172)] + fix_aspect(target, 3, 9, 4, 5, writeback=0), 0x023B9AC),
        (0x033B82C, 0x2D558440, [ldp_s(0, 1, 2, 172)] + fix_aspect(target, 1, 9, 2, 3, writeback=2), 0x033B830),
        # render view setup: scvtf s1, w21 ; fdiv s1, s1, s2 (aspect = w / h), resumes after the fdiv
        (0x025D76C, 0x1E2202A1, [scvtf_sw(1, 21), fdiv(1, 1, 2)] + fix_aspect(target, 1, 16, 16, 17), 0x025D774),
        # 2D canvas: projection * view -> canvas matrices (main+0x774330)
        (0x0774368, 0xAD401041, squash_ui(row, f32(squash)), 0x077436C),
        # pre-rendered movie layer draw (main+0x3B5C71C): ldp x9, x8, [x19, #24]
        (0x3B5C758, 0xA941A269, box_movie(f32((1 - squash) / 2), viewport_lo), 0x3B5C75C),
        # NPC speech bubble anchor (layout x = ndc x * 1920, y = ndc y * 1080): mov w8, #1920.0 (or #1080.0)
        # -> half / squash, so the squeezed canvas puts the bubble back over its speaker
        (anchor, anchor_word, [movz(8, f32(half / squash) & 0xFFFF), movk16(8, f32(half / squash) >> 16)], anchor + 4),
        # graphics allocator setup: stp x8, x9, [sp, #16] stores the pool's initial size (x8). Doubled, as
        # Lichii PR #976's "Texture Pool x2" does: the wider picture's render targets ran the pool out when
        # an item was collected (a null target linked into a list, then an endless walk of it)
        (0x0C2A36C, 0xA90127E8, [lsl_x(8, 8, 1), 0xA90127E8], 0x0C2A370),
    ]


def picture_size(w, h):
    """(module offset, original word, new word): the picture the game renders (2560x1440) and the scene
    its upscaler takes in (1920x1080, 3/4 of it), each built in x8 by a mov (width) and a movk (height).
    The same sites as NX2navi's wide_out / wide_scene (recomp/patches-v111.txt) and Hookshot's
    nx2/oot_wide.py."""
    assert w % 4 == 0 and h % 4 == 0
    sw, sh = w * 3 // 4, h * 3 // 4
    assert movz_x(8, 2560) == 0xD2814008 and movz_x(8, 1920) == 0xD280F008
    assert movk_x32(8, 1440) == 0xF2C0B408 and movk_x32(8, 1080) == 0xF2C08708
    return [
        (0x1202EE0, movz_x(8, 2560), movz_x(8, w)), (0x1202EE4, movk_x32(8, 1440), movk_x32(8, h)),  # graphics setup
        (0x31F39F4, movz_x(8, 2560), movz_x(8, w)), (0x31F39F8, movk_x32(8, 1440), movk_x32(8, h)),  # display settings
        (0x31F3A00, movz_x(8, 1920), movz_x(8, sw)), (0x31F3A04, movk_x32(8, 1080), movk_x32(8, sh)),  # the scene
    ]


def edits(aspect, w, h):
    """(module offset, original word, new word)"""
    out, cave = picture_size(w, h), CAVE_BASE
    for hook, original, body, back in hooks(aspect):
        words = body + [branch(cave + 4 * len(body), back)]
        out.append((hook, original, branch(hook, cave)))
        out += [(cave + 4 * k, 0, w(cave + 4 * k) if callable(w) else w) for k, w in enumerate(words)]
        cave += 4 * len(words)
    assert cave <= 0x3C47000, "caves overflow the executable padding"
    return out


def ips32(records):
    blob = bytearray(b"IPS32")
    for offset, _, word in sorted(records):
        blob += struct.pack(">IH", offset + NSO_HEADER_SIZE, 4) + struct.pack("<I", word)
    return bytes(blob + b"EEOF")


def parse_ips32(blob):
    assert blob[:5] == b"IPS32" and blob[-4:] == b"EEOF"
    pos, recs = 5, {}
    while pos < len(blob) - 4:
        offset, size = struct.unpack_from(">IH", blob, pos)
        recs[offset - NSO_HEADER_SIZE] = struct.unpack_from("<I", blob, pos + 6)[0]
        pos += 6 + size
    assert pos == len(blob) - 4
    return recs


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--verify-main", type=Path, help="raw main module image (module offset 0 = file offset 0)")
    p.add_argument("--output-dir", type=Path, default=Path(__file__).parent / "releases")
    args = p.parse_args()
    image = args.verify_main.read_bytes() if args.verify_main else None
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, (zip_name, aspect, w, h) in VARIANTS.items():
        recs = edits(aspect, w, h)
        if image:
            for offset, original, _ in recs:
                found = struct.unpack_from("<I", image, offset)[0]
                assert found == original, f"main+{offset:#x}: expected {original:#010x}, found {found:#010x}"
        patch = ips32(recs)
        assert parse_ips32(patch) == {o: w for o, _, w in recs}
        member = f"{TITLE_ID}/{name}/exefs/{BUILD_ID}.ips"
        info = zipfile.ZipInfo(member, date_time=(1980, 1, 1, 0, 0, 0))  # fixed date: reproducible zips
        info.external_attr = 0o644 << 16
        info.create_system = 3  # Unix, as on Linux and macOS, so Windows builds give the same bytes
        target = args.output_dir / zip_name
        with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as z:
            z.writestr(info, patch)
        with zipfile.ZipFile(target) as z:
            assert z.testzip() is None and z.read(member) == patch
        print(target, "->", member, f"({len(recs)} records)")
