"""An owned synthetic screenshot for checking real vision inference safely."""
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def sample_screen():
    def font(size, mono=False):
        path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / ("consola.ttf" if mono else "segoeui.ttf")
        return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)
    image = Image.new("RGB", (1120, 760), "#101925")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1120, 58), fill="#223149")
    draw.text((28, 15), "Example Editor — authentication.ts", font=font(22), fill="white")
    draw.text((36, 95), "EXAMPLE PROJECT / src / authentication.ts", font=font(19), fill="#a8bbd1")
    code = ["function showUser(user) {", "  return user.id;", "}", "", "showUser(undefined);"]
    for index, line in enumerate(code):
        draw.text((42, 158 + index * 34), f"{index + 1:2}   {line}", font=font(23, True), fill="#dce9f7")
    draw.rectangle((28, 396, 1090, 696), fill="#351e29", outline="#d36b76", width=2)
    draw.text((50, 422), "Build failed", font=font(29), fill="#ffb4bb")
    draw.text((50, 480), "TypeError: Cannot read properties of undefined", font=font(24, True), fill="white")
    draw.text((50, 523), "(reading 'id')", font=font(24, True), fill="white")
    draw.text((50, 582), "at showUser (authentication.ts:2:15)", font=font(22, True), fill="#e5bdc7")
    draw.text((50, 635), "1 error   |   0 warnings", font=font(21), fill="#e5bdc7")
    draw.text((32, 718), "Synthetic test screen. No desktop capture or private content.", font=font(16), fill="#94a9c2")
    return image


def sample_video():
    """Eight owned frames with a visible red-error to green-success transition."""
    from .video import ScreenClip, ScreenFrame
    from datetime import datetime, timedelta, timezone
    start = datetime.now(timezone.utc)
    frames = []
    for index in range(8):
        image = sample_screen()
        draw = ImageDraw.Draw(image)
        if index >= 4:
            draw.rectangle((28, 396, 1090, 696), fill="#123326", outline="#70dc9c", width=3)
            path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeui.ttf"
            font = ImageFont.truetype(str(path), 42) if path.exists() else ImageFont.load_default(size=42)
            draw.text((55, 450), "BUILD SUCCEEDED", font=font, fill="#96ffb6")
            draw.text((55, 530), "0 errors   |   0 warnings", font=font, fill="white")
        frames.append(ScreenFrame(image.resize((960, 672)), (start + timedelta(seconds=index)).isoformat(),
                                  float(index), "Example Editor", "authentication.ts"))
    return ScreenClip(tuple(frames))

