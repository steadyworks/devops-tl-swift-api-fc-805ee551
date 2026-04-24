from enum import Enum


class CompressionTier(str, Enum):
    HIGH_END_DISPLAY = "high_end_display"  # asset_key_display
    # MOBILE_DISPLAY = "mobile_display"
    LLM = "llm"  # asset_key_llm
    THUMBNAIL = "thumbnail"
    PLACEHOLDER_BLUR = "placeholder_blur"
