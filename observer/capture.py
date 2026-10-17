from PIL import Image, ImageChops, ImageDraw


class ScreenCapture:
    def __init__(self):
        import mss
        self.backend = mss.MSS()

    def grab(self, window, excluded_windows):
        # MSS reports physical pixels; foreground rectangles share the same DPI context.
        desktop = self.backend.monitors[0]
        left = max(window.rect[0], desktop["left"])
        top = max(window.rect[1], desktop["top"])
        right = min(window.rect[2], desktop["left"] + desktop["width"])
        bottom = min(window.rect[3], desktop["top"] + desktop["height"])
        if right <= left or bottom <= top:
            raise ValueError("The active window is outside the current displays.")
        shot = self.backend.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        draw = ImageDraw.Draw(image)
        for other in excluded_windows:
            x1, y1, x2, y2 = other.rect
            box = (max(0, x1 - left), max(0, y1 - top), min(image.width, x2 - left), min(image.height, y2 - top))
            if box[2] > box[0] and box[3] > box[1]:
                draw.rectangle(box, fill="#151d29")
        image.thumbnail((1440, 1000))
        return image

    def close(self):
        self.backend.close()


def fingerprint(image):
    return image.convert("L").resize((96, 64))


def difference(previous, current) -> float:
    if previous is None:
        return 1.0
    histogram = ImageChops.difference(previous, current).histogram()
    return sum(histogram[21:]) / (current.width * current.height)

