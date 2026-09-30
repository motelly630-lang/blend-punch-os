"""진공 초당 & 찰 옥수수 광고 소재 2차 — 우리 상품 GIF·사진만 (미니 옥수수 영상 제외, 2026-09-29 대표님 확인).

후킹 3초 × 본문 4장면(각 2.25초, 작은 자막) × 마지막 3초 = 15초, 세로 1080x1920, 소리 없음.
가로 GIF 는 흐린 배경 위 가운데. 문구는 대표님이 확인한 것만: 소비기한 18개월 · 전자레인지 OK · 환경호르몬 NO · 실온 보관.
사용: uv run python scripts/ads/corn_variants_v2.py [--only 1]   → ~/Desktop/광고소재/진공옥수수/소재_출력_2차/
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path.home() / "Desktop/광고소재/진공옥수수"
OUT = SRC / "소재_출력_2차"
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
W, H, FPS = 1080, 1920, 30
HOOK_SEC, SHOT_SEC, END_SEC = 3.0, 2.25, 3.0
PRODUCT = "진공 초당 & 찰 옥수수"


def g(name):
    return SRC / name


HOOKS = [
    (1, g("4.gif"), "옥수수 삶기,\n아직도 하세요?"),
    (2, g("10.gif"), "봉지째\n전자레인지 OK"),
    (3, g("03.gif"), "실온 보관\n소비기한 18개월"),
    (4, g("05.gif"), "환경호르몬 NO\n진공 포장"),
    (5, g("32.gif"), "당일 새벽 수확,\n바로 진공"),
    (6, g("6.gif"), "쫀득 탱글\n초당옥수수"),
    (7, g("옥수수.gif"), "한 입에\n똑"),
    (8, g("00.gif"), "냉동실 자리 차지\nNO"),
    (9, g("8.gif"), "절단면만 톡,\n손질 NO"),
    (10, g("13.jpeg"), "삶을 필요 없는\n옥수수"),
]
BODIES = {
    "A": [(g("34.gif"), "당일 새벽 수확"), (g("00.gif"), "바로 진공 포장"),
          (g("10.gif"), "봉지째 전자레인지 OK"), (g("옥수수.gif"), "쫀득하게 똑")],
    "B": [(g("10.gif"), "전자레인지 · 끓는 물 OK"), (g("8.gif"), "절단면만 톡"),
          (g("6.gif"), "쫀득 탱글"), (g("03.gif"), "실온 보관 18개월")],
}
END = (g("00.gif"), [PRODUCT, "산지픽에서 만나요"])


def font(size):
    return ImageFont.truetype(FONT, size, index=6)


def text_png(path, lines, top, size, first_yellow=True):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(size)
    hs = [d.textbbox((0, 0), ln, font=f)[3] for ln in lines]
    gap = int(size * 0.25)
    total = sum(hs) + gap * (len(lines) - 1)
    d.rounded_rectangle([40, top - 40, W - 40, top + total + 50], radius=36, fill=(0, 0, 0, 170))
    y = top
    for i, (ln, h) in enumerate(zip(lines, hs)):
        tw = d.textbbox((0, 0), ln, font=f)[2]
        color = (255, 221, 0, 255) if (i == 0 and first_yellow) else (255, 255, 255, 255)
        d.text(((W - tw) / 2, y), ln, font=f, fill=color, stroke_width=4, stroke_fill=(0, 0, 0, 255))
        y += h + gap
    im.save(path)


def src_input(src: Path, dur: float) -> list:
    if src.suffix == ".gif":
        return ["-ignore_loop", "0", "-t", str(dur + 0.5), "-i", str(src)]
    return ["-loop", "1", "-t", str(dur + 0.5), "-i", str(src)]


def shot(idx: int, dur: float, lab: str) -> str:
    """입력 idx → 1080x1920 (흐린 배경 + 가운데), 길이 dur."""
    return (f"[{idx}:v]fps={FPS},setpts=PTS-STARTPTS,split[{lab}a][{lab}b];"
            f"[{lab}a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:5[{lab}bg];"
            f"[{lab}b]scale={W}:-2[{lab}fg];[{lab}bg][{lab}fg]overlay=(W-w)/2:(H-h)/2,"
            f"trim=duration={dur},setpts=PTS-STARTPTS,setsar=1,format=yuv420p[{lab}]")


def build(hook, bname, tmp: Path) -> Path:
    n, hsrc, htext = hook
    shots = [(hsrc, HOOK_SEC, htext.split("\n"), 300, 92, True)]
    shots += [(s, SHOT_SEC, [cap], 480, 72, False) for s, cap in BODIES[bname]]
    shots.append((END[0], END_SEC, END[1], 1020, 70, True))
    args, parts, labels = [], [], []
    for i, (s, dur, _, _, _, _) in enumerate(shots):
        args += src_input(s, dur)
    base = len(shots)
    for i, (s, dur, lines, top, size, yellow) in enumerate(shots):
        png = tmp / f"t{n}_{bname}_{i}.png"
        text_png(png, lines, top, size, yellow)
        args += ["-loop", "1", "-t", str(dur), "-i", str(png)]
        parts.append(shot(i, dur, f"s{i}"))
        parts.append(f"[s{i}][{base + i}:v]overlay=0:0[o{i}]")
        labels.append(f"[o{i}]")
    parts.append("".join(labels) + f"concat=n={len(shots)}:v=1:a=0[out]")
    out = OUT / f"진공옥수수_후킹{n:02d}_본문{bname}.mp4"
    cmd = (["ffmpeg", "-v", "error", "-y"] + args
           + ["-filter_complex", ";".join(parts), "-map", "[out]", "-an", "-c:v", "libx264", "-crf", "20",
              "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)])
    subprocess.run(cmd, check=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int)
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        for h in HOOKS:
            if a.only and h[0] != a.only:
                continue
            for b in (["A"] if a.only else ["A", "B"]):
                print("만듦:", build(h, b, Path(t)).name)


if __name__ == "__main__":
    main()
