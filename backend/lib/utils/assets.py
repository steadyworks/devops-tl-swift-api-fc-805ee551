from typing import Optional

_ACCEPTED_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


def is_accepted_mime(mime: Optional[str]) -> bool:
    return mime is not None and (
        mime.startswith("image/")
        # or mime.startswith("video/") # FIXME / TODO: only images allowed for now
    )


def is_accepted_asset_ext_photos(ext: str) -> bool:
    return ext.lower() in _ACCEPTED_PHOTO_EXTS
