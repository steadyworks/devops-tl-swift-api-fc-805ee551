import logging
from pathlib import Path
from typing import Any, Mapping, Optional

import piexif
import piexif._exceptions
from piexif._exif import GPSIFD, ExifIFD, ImageIFD
from PIL import Image as PILImage

from backend.db.data_models.types import ExtractedExif

# ------------------------- internal helpers ------------------------- #


def _ratio_to_float(ratio: Any) -> Optional[float]:
    """
    Convert an EXIF rational (num, denom) tuple to float.
    Returns None on malformed input.
    """
    try:
        num, denom = ratio
        return float(num) / float(denom) if denom else None
    except Exception:
        return None


def _dms_to_decimal(dms: Any, ref: str) -> Optional[float]:
    """
    Convert EXIF degrees / minutes / seconds + hemisphere ref to decimal degrees.
    """
    if not dms or len(dms) != 3:
        return None
    try:
        degrees = _ratio_to_float(dms[0])
        minutes = _ratio_to_float(dms[1])
        seconds = _ratio_to_float(dms[2])
        if degrees is None or minutes is None or seconds is None:
            return None
        decimal = degrees + minutes / 60.0 + seconds / 3600.0
        return -decimal if ref in ("S", "W") else decimal
    except Exception:
        return None


def _parse_exif_dict(exif_dict: Mapping[str, Any]) -> Optional[ExtractedExif]:
    """
    Convert piexif dict → ExtractedExif TypedDict.  Never raises.
    """
    result: Optional[ExtractedExif] = None
    try:
        zeroth = exif_dict.get("0th", {})
        exif_sub = exif_dict.get("Exif", {})
        gps_sub = exif_dict.get("GPS", {})
        # GPS
        gps_lat = gps_sub.get(GPSIFD.GPSLatitude)
        gps_lon = gps_sub.get(GPSIFD.GPSLongitude)
        ref_lat = (
            gps_sub.get(GPSIFD.GPSLatitudeRef, b"N").decode(errors="ignore") or "N"
        )
        ref_lon = (
            gps_sub.get(GPSIFD.GPSLongitudeRef, b"E").decode(errors="ignore") or "E"
        )

        lat = _dms_to_decimal(gps_lat, ref_lat)
        lon = _dms_to_decimal(gps_lon, ref_lon)

        result = ExtractedExif(
            make=zeroth.get(ImageIFD.Make, b"").decode(errors="ignore"),
            model=zeroth.get(ImageIFD.Model, b"").decode(errors="ignore"),
            datetime_original=exif_sub.get(ExifIFD.DateTimeOriginal, b"").decode(
                errors="ignore"
            ),
            iso=int(exif_sub.get(ExifIFD.ISOSpeedRatings, 0) or 0),
            exposure_time=(
                _ratio_to_float(exif_sub.get(ExifIFD.ExposureTime, (0, 1)) or (0, 1))
                or 0.0
            ),
            fnumber=(
                _ratio_to_float(exif_sub.get(ExifIFD.FNumber, (0, 1)) or (0, 1)) or 0.0
            ),
            focal_length=(
                _ratio_to_float(exif_sub.get(ExifIFD.FocalLength, (0, 1)) or (0, 1))
                or 0.0
            ),
            gps_latitude=lat,
            gps_longitude=lon,
        )

    except Exception as parse_err:
        logging.exception("[EXIF] Parse failure: %s", parse_err)

    return result


# --------------------------- public API ----------------------------- #


def extract_exif_fields(input_path: Path) -> Optional[ExtractedExif]:
    """Open file → grab EXIF bytes → delegate parsing."""

    suffix = input_path.suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".tif", ".tiff"}:
        logging.debug("[EXIF] Skipping non-JPEG/TIFF: %s", input_path)
        return None

    try:
        with PILImage.open(input_path) as img:
            raw_exif: bytes | None = img.info.get("exif")  # pyright: ignore[attr-defined]
    except (FileNotFoundError, PermissionError, OSError) as io_err:
        logging.warning("[EXIF] File error on %s: %s", input_path, io_err)
        return None

    if not raw_exif:
        logging.debug("[EXIF] No EXIF in %s", input_path)
        return None

    # All parse-level handling lives inside this helper
    return extract_exif_from_bytes(raw_exif)


def extract_exif_from_bytes(raw_exif: bytes) -> Optional[ExtractedExif]:
    """
    Parse EXIF given a raw APP1/TIFF blob.
    Returns None on any problem; never raises (except MemoryError).
    """
    if not raw_exif:
        return None

    try:
        exif_dict = piexif.load(raw_exif)  # pyright: ignore[reportArgumentType]  (bytes runtime OK)
        return _parse_exif_dict(exif_dict)
    except (piexif._exceptions.InvalidImageDataError, ValueError) as bad:
        logging.debug("[EXIF] Invalid EXIF bytes: %s", bad)
        return None
    except MemoryError:
        logging.critical("[EXIF] OOM parsing raw bytes (%d B)", len(raw_exif))
        raise
    except Exception as unexpected:
        logging.exception("[EXIF] Unexpected error parsing bytes: %s", unexpected)
        return None
