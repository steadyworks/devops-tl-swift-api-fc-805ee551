from typing import Any, TypedDict

ExifDict = TypedDict(
    "ExifDict",
    {
        "0th": dict[int, Any],
        "Exif": dict[int, Any],
        "GPS": dict[int, Any],
        "1st": dict[int, Any],
        "thumbnail": bytes,
    },
    total=False,
)

def load(input_data: str, key_is_name: bool = False) -> ExifDict: ...
def dump(exif_dict: ExifDict) -> bytes: ...
def insert(exif_bytes: bytes, filename: str) -> None: ...
