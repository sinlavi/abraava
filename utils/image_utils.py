from PIL import Image
import io

def crop_to_square(image_bytes: bytes) -> bytes:
    """Crops an image to a center square."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        width, height = img.size

        if width == height:
            return image_bytes

        new_size = min(width, height)
        left = (width - new_size) / 2
        top = (height - new_size) / 2
        right = (width + new_size) / 2
        bottom = (height + new_size) / 2

        img = img.crop((left, top, right, bottom))

        output = io.BytesIO()
        # Preserve original format if possible, fallback to JPEG
        fmt = img.format if img.format else "JPEG"
        img.save(output, format=fmt, quality=95)
        return output.getvalue()
    except Exception:
        return image_bytes
