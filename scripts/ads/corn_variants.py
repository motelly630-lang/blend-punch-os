"""진공 옥수수 광고 소재 조합기 — 후킹(3초) × 본문(8초) × 마지막 화면(3초), 세로 1080x1920, 소리 없음.

사용: uv run python scripts/ads/corn_variants.py [--only 1]   (결과: ~/Desktop/광고소재/진공옥수수/소재_출력/)
"""
import argparse
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path.home() / "Desktop/광고소재/진공옥수수"
OUT = SRC / "소재_출력"
V1 = SRC / "KakaoTalk_Video_2026-09-29-19-51-46.mp4"
V2 = SRC / "KakaoTalk_Video_2026-09-29-19-51-58.mp4"
FONT = "/System/Library/Fonts/AppleSDGothicNeo.ttc"
W, H, FPS = 1080, 1920, 30

# (번호, 소스, 시작초, 후킹 문구)
HOOKS = [
    (1, V1, 0.0, "이 옥수수,\n왜 품절일까요?"),
    (2, V1, 3.0, "사두면 금방\n없어지는 옥수수"),
    (3, V1, 7.5, "봉지째 전자레인지\n1분 30초 끝"),
    (4, V1, 9.5, "실온 보관\n소비기한 18개월"),
    (5, V1, 13.5, "길에서 사 먹는 옥수수\n원산지 보셨어요?"),
    (6, V2, 11.5, "혹시 중국산 옥수수\n드시고 계세요?"),
    (7, V2, 13.5, "큰 옥수수\n아이가 다 못 먹죠?"),
    (8, V1, 23.5, "아이 손에 딱\n아기 옥수수"),
    (9, SRC / "옥수수.gif", 0.0, "쫀득 탱글\n한 입에 똑"),
    (10, V1, 29.5, "환경호르몬\n불검출 인증"),
]
BODIES = [("A", V1, 20.5, 8.0), ("B", V2, 13.5, 8.0)]
END = (V2, 26.5, 3.0, "클래식 미니 초당·찰옥수수", "산지픽에서 만나요")
HOOK_SEC = 3.0


def font(size):
    return ImageFont.truetype(FONT, size, index=6)


def text_png(path, lines, top, size, box=True):
    """투명 1080x1920 위에 가운데 정렬 글자 + 반투명 검은 띠."""
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font(size)
    heights = [d.textbbox((0, 0), ln, font=f)[3] for ln in lines]
    gap = int(size * 0.25)
    total = sum(heights) + gap * (len(lines) - 1)
    if box:
        d.rounded_rectangle([40, top - 40, W - 40, top + total + 50], radius=36, fill=(0, 0, 0, 170))
    y = top
    for ln, hgt in zip(lines, heights):
        tw = d.textbbox((0, 0), ln, font=f)[2]
        d.text(((W - tw) / 2, y), ln, font=f, fill=(255, 221, 0, 255) if ln is lines[0] else (255, 255, 255, 255),
               stroke_width=4, stroke_fill=(0, 0, 0, 255))
        y += hgt + gap
    im.save(path)


def norm(src: Path, start: float, dur: float, label: str) -> str:
    """입력 하나를 1080x1920·30fps 로. 가로 소재(GIF)는 흐린 배경 위에 가운데."""
    if src.suffix == ".gif":
        return (f"[{label}]fps={FPS},setpts=PTS-STARTPTS,split[{label}a][{label}b];"
                f"[{label}a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:5[{label}bg];"
                f"[{label}b]scale={W}:-2[{label}fg];[{label}bg][{label}fg]overlay=(W-w)/2:(H-h)/2,"
                f"trim=duration={dur},setsar=1,format=yuv420p[{label}n]")
    return (f"[{label}]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
            f"setpts=PTS-STARTPTS,setsar=1,format=yuv420p[{label}n]")


def inp(src: Path, start: float, dur: float) -> list:
    if src.suffix == ".gif":
        return ["-ignore_loop", "0", "-t", str(dur + 0.5), "-i", str(src)]
    return ["-ss", str(start), "-t", str(dur), "-i", str(src)]


def build(hook, body, tmp: Path) -> Path:
    n, hsrc, hstart, htext = hook
    bname, bsrc, bstart, bdur = body
    esrc, estart, edur, e1, e2 = END
    hp, ep = tmp / f"h{n}.png", tmp / "end.png"
    text_png(hp, htext.split("\n"), 300, 92)
    text_png(ep, [e1, e2], 1020, 70)
    out = OUT / f"옥수수_후킹{n:02d}_본문{bname}.mp4"
    fc = ";".join([
        norm(hsrc, hstart, HOOK_SEC, "0:v").replace("[0:v]", "[0:v]", 1),
        norm(bsrc, bstart, bdur, "1:v"),
        norm(esrc, estart, edur, "2:v"),
        "[0:vn][3:v]overlay=0:0[h]",
        "[2:vn][4:v]overlay=0:0[e]",
        "[h][1:vn][e]concat=n=3:v=1:a=0[out]",
    ])
    # 라벨 이름 정리 (ffmpeg 라벨에 ':' 를 못 쓰므로)
    fc = fc.replace("[0:va]", "[ha]").replace("[0:vb]", "[hb]").replace("[0:vbg]", "[hbg]").replace("[0:vfg]", "[hfg]")
    fc = fc.replace("[0:vn]", "[hn]").replace("[1:vn]", "[bn]").replace("[2:vn]", "[en]")
    fc = fc.replace("[2:va]", "[ea]").replace("[2:vb]", "[eb]").replace("[2:vbg]", "[ebg]").replace("[2:vfg]", "[efg]")
    cmd = (["ffmpeg", "-v", "error", "-y"] + inp(hsrc, hstart, HOOK_SEC) + inp(bsrc, bstart, bdur)
           + inp(esrc, estart, edur) + ["-loop", "1", "-t", str(HOOK_SEC), "-i", str(hp),
                                        "-loop", "1", "-t", str(edur), "-i", str(ep)]
           + ["-filter_complex", fc, "-map", "[out]", "-an", "-c:v", "libx264", "-crf", "20",
              "-preset", "medium", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)])
    subprocess.run(cmd, check=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, help="후킹 번호 하나만 (본문 A)")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        jobs = [(h, b) for h in HOOKS for b in BODIES]
        if a.only:
            jobs = [(h, b) for h, b in jobs if h[0] == a.only and b[0] == "A"]
        for h, b in jobs:
            print("만듦:", build(h, b, tmp).name)


if __name__ == "__main__":
    main()
