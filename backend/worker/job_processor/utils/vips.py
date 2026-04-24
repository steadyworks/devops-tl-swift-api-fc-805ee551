import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Sequence

from pyvips import Image
from pyvips.enums import Size

from backend.db.data_models.types import ExtractedExif

from .exif import extract_exif_from_bytes
from .types import CompressionTier

logging.getLogger("pyvips").setLevel(logging.WARNING)

DEFAULT_TIMEOUT_PER_IMAGE_SECS = 5


@dataclass(frozen=True)
class CompressionSettings:
    max_size: int
    quality: int


COMPRESSION_SETTING_PRESETS: dict[CompressionTier, CompressionSettings] = {
    CompressionTier.HIGH_END_DISPLAY: CompressionSettings(max_size=2048, quality=85),
    # CompressionTier.MOBILE_DISPLAY: CompressionSettings(max_size=1250, quality=85),
    CompressionTier.LLM: CompressionSettings(max_size=1000, quality=80),
    CompressionTier.THUMBNAIL: CompressionSettings(max_size=180, quality=80),
    CompressionTier.PLACEHOLDER_BLUR: CompressionSettings(max_size=20, quality=50),
}


@dataclass
class ImageProcessingResult:
    is_compress_succeeded: bool
    compressed_path: Optional[Path]
    exif_result: Optional[ExtractedExif]


class ImageProcessingLibrary:
    def __init__(
        self,
        max_concurrent: int,
        timeout_secs: int | float = DEFAULT_TIMEOUT_PER_IMAGE_SECS,
    ) -> None:
        self._sema = asyncio.Semaphore(max_concurrent)
        self._timeout_secs = timeout_secs

    async def compress_by_tier_on_thread(
        self,
        input_paths: Sequence[str | Path],
        output_dir: str | Path,
        format: Literal["jpeg", "webp"],
        tier: CompressionTier,
        strip_metadata: bool,
    ) -> dict[Path, ImageProcessingResult]:
        settings = COMPRESSION_SETTING_PRESETS[tier]
        return await self._compress_images_on_thread(
            image_path_report_path_list=[
                (input_path, input_path) for input_path in input_paths
            ],
            output_dir=output_dir,
            format=format,
            max_size=settings.max_size,
            quality=settings.quality,
            strip_metadata=strip_metadata,
            processed_filename_suffix=tier.value,
        )

    async def compress_by_tier_from_compressed_on_thread(
        self,
        input_path_compressed_path_map: dict[str | Path, Optional[str | Path]],
        output_dir: str | Path,
        format: Literal["jpeg", "webp"],
        tier: CompressionTier,
        strip_metadata: bool,
    ) -> dict[Path, ImageProcessingResult]:
        settings = COMPRESSION_SETTING_PRESETS[tier]
        return await self._compress_images_on_thread(
            image_path_report_path_list=[
                (compressed_path or input_path, input_path)
                for (
                    input_path,
                    compressed_path,
                ) in input_path_compressed_path_map.items()
            ],
            output_dir=output_dir,
            format=format,
            max_size=settings.max_size,
            quality=settings.quality,
            strip_metadata=strip_metadata,
            processed_filename_suffix=tier.value,
        )

    async def _compress_images_on_thread(
        self,
        image_path_report_path_list: Sequence[tuple[str | Path, str | Path]],
        output_dir: str | Path,
        format: Literal["jpeg", "webp"],
        max_size: int,
        quality: int,
        strip_metadata: bool,
        processed_filename_suffix: str,
    ) -> dict[Path, ImageProcessingResult]:
        output_dir = Path(output_dir)
        if not output_dir.is_dir():
            raise FileNotFoundError(
                f"[ImageProcessingLibrary] Output directory does not exist: {output_dir}"
            )

        results: dict[Path, ImageProcessingResult] = {}
        for image_path, report_path in image_path_report_path_list:
            image_path = Path(image_path)
            report_path = Path(report_path)
            async with self._sema:
                try:
                    res = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._compress_image_sync,
                            image_path,
                            output_dir,
                            Path(report_path).stem,
                            format,
                            max_size,
                            quality,
                            strip_metadata,
                            processed_filename_suffix=processed_filename_suffix,
                        ),
                        timeout=self._timeout_secs,
                    )
                    results[report_path] = ImageProcessingResult(
                        is_compress_succeeded=res.is_compress_succeeded,
                        compressed_path=res.compressed_path
                        if res.is_compress_succeeded
                        else None,
                        exif_result=res.exif_result,
                    )
                except asyncio.TimeoutError:
                    logging.warning(f"[ImageLibrary] Timeout on {report_path}")
                    results[report_path] = ImageProcessingResult(
                        is_compress_succeeded=False,
                        compressed_path=None,
                        exif_result=None,
                    )
                except Exception as e:
                    logging.exception(
                        f"[ImageLibrary] Compression failed for {report_path}: {e}"
                    )
                    results[report_path] = ImageProcessingResult(
                        is_compress_succeeded=False,
                        compressed_path=None,
                        exif_result=None,
                    )

        return results

    def _compress_image_sync(
        self,
        input_path: str | Path,
        output_dir: str | Path,
        base_name: str,
        format: str,
        max_size: int,
        quality: int,
        strip_metadata: bool,
        processed_filename_suffix: str,
    ) -> ImageProcessingResult:
        input_path = Path(input_path)
        output_dir = Path(output_dir)

        # Normalize format
        format = format.lower()
        normalized_format = "jpeg" if format in {"jpeg", "jpg"} else format
        ext = "jpg" if normalized_format == "jpeg" else normalized_format
        output_path = output_dir / f"{base_name}.{processed_filename_suffix}.{ext}"

        exif_info: Optional[ExtractedExif] = None
        try:
            start = time.monotonic()

            # quick header read to decide whether to short-circuit
            header = Image.new_from_file(str(input_path), access="sequential")

            try:
                if not strip_metadata:
                    raw_exif = (
                        header.get("exif-data") or b""
                    )  # libvips stores bytes here
                    exif_info = extract_exif_from_bytes(raw_exif)
            except Exception as e:
                logging.info(
                    f"[ImageProcessingLibrary] ignoring exif extraction failure: {e}"
                )

            no_resize_needed = max(header.width, header.height) <= max_size
            is_jpeg = header.format.lower() in {"jpeg", "jpg"}
            is_webp = header.format.lower() == "webp"
            format_matches = (normalized_format == "jpeg" and is_jpeg) or (
                normalized_format == "webp" and is_webp
            )

            if no_resize_needed and format_matches and not strip_metadata:
                try:
                    shutil.copy2(input_path, output_path)
                    logging.info(
                        "[ImageLibrary] Skipped compression; copied to %s", output_path
                    )
                    return ImageProcessingResult(
                        is_compress_succeeded=True,
                        compressed_path=output_path,
                        exif_result=exif_info,
                    )
                except Exception as copy_err:
                    logging.warning("[ImageLibrary] Failed to copy: %s", copy_err)
                    return ImageProcessingResult(
                        is_compress_succeeded=False,
                        compressed_path=None,
                        exif_result=exif_info,
                    )

            # --- fast path: shrink-on-load ------------------------------------
            image = Image.thumbnail(
                str(input_path),
                max_size,
                size=Size.DOWN,  # power-of-two shrink in decoder
            )
            logging.info(
                "[Timing %s] thumbnail(): %.2fs",
                input_path,
                time.monotonic() - start,
            )

            # save; libvips preserves EXIF unless strip=True
            save_opts = self._get_save_options(
                normalized_format, quality, strip_metadata
            )
            image.write_to_file(str(output_path), **save_opts)

            logging.info(
                "[Timing %s] write_to_file: %.2fs",
                input_path,
                time.monotonic() - start,
            )
            logging.debug("[ImageLibrary] Compressed image written to %s", output_path)
            return ImageProcessingResult(
                is_compress_succeeded=True,
                compressed_path=output_path,
                exif_result=exif_info,
            )

        except Exception as e:
            logging.warning(
                "[ImageLibrary] Compression failed for %s: %s", input_path, e
            )
            return ImageProcessingResult(
                is_compress_succeeded=False, compressed_path=None, exif_result=exif_info
            )

    @staticmethod
    def _compute_scale(width: int, height: int, max_size: int) -> float:
        return min(1.0, max_size / max(width, height))

    @staticmethod
    def _get_save_options(
        format: str, quality: int, strip: bool
    ) -> dict[str, int | bool]:
        if format == "jpeg":
            return dict(
                Q=quality,
                optimize_coding=True,
                interlace=True,  # no progressive scans
                trellis_quant=False,
                overshoot_deringing=False,
                strip=strip,
            )
        if format == "webp":
            return dict(
                Q=quality,
                effort=1,  # 0–6, 1 is fastest
                strip=strip,
            )
        raise ValueError(f"unsupported format {format}")
