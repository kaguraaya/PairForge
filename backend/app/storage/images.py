from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError


class InvalidImageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StoredImage:
    path: Path
    sha256: str
    width: int
    height: int
    mime_type: str
    file_size: int


def validate_image(data: bytes, *, minimum_bytes: int = 64) -> tuple[int, int, str, str]:
    if len(data) < minimum_bytes:
        raise InvalidImageError("图片数据过短")
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            image_format = image.format or "PNG"
    except (UnidentifiedImageError, OSError) as error:
        raise InvalidImageError("返回内容不是有效图片") from error
    if width < 16 or height < 16:
        raise InvalidImageError("图片尺寸过小")
    mime_type = Image.MIME.get(image_format, f"image/{image_format.lower()}")
    extension = ".jpg" if image_format.upper() == "JPEG" else f".{image_format.lower()}"
    return width, height, mime_type, extension


def store_image_atomic(data: bytes, destination: Path) -> StoredImage:
    width, height, mime_type, _extension = validate_image(data)
    destination.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.stem}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return StoredImage(
        path=destination,
        sha256=hashlib.sha256(data).hexdigest(),
        width=width,
        height=height,
        mime_type=mime_type,
        file_size=len(data),
    )

