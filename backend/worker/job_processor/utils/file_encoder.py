import asyncio
import base64
import mimetypes
from pathlib import Path
from typing import Optional


def encode_file_as_data_url(path: Path) -> Optional[str]:
    try:
        if not path.is_file():
            return None
        mime_type, _ = mimetypes.guess_type(path)
        if not mime_type:
            mime_type = "image/jpeg"
        with path.open("rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime_type};base64,{b64}"
    except Exception:
        return None


async def encode_files_to_data_urls(
    paths: list[Path],
    max_concurrent: int = 10,
) -> dict[Path, Optional[str]]:
    semaphore = asyncio.Semaphore(max_concurrent)

    async def safe_encode(path: Path) -> tuple[Path, Optional[str]]:
        async with semaphore:
            result = await asyncio.to_thread(encode_file_as_data_url, path)
            return path, result

    tasks = [safe_encode(path) for path in paths]
    results = await asyncio.gather(*tasks)
    return dict(results)
