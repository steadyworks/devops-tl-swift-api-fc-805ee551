from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel


class JobType(Enum):
    # Local job types
    LOCAL_ASSET_COMPRESS_UPLOAD = "local_asset_compress_upload"

    # Remote job types
    REMOTE_PHOTOBOOK_GENERATION = "remote_photobook_generation"
    REMOTE_POST_PROCESS_UPLOADED_ASSETS = "remote_post_process_uploaded_assets"


class JobInputPayload(BaseModel):
    owner_id: UUID
    user_id: Optional[UUID]
    originating_photobook_id: Optional[UUID]


class JobOutputPayload(BaseModel):
    job_id: UUID


#####################################################################################
# Local processor input / output
#####################################################################################


#####################################################################################
# Remote processor input / output
#####################################################################################
class PhotobookGenerationInputPayload(JobInputPayload):
    asset_ids: list[UUID]


class PhotobookGenerationOutputPayload(JobOutputPayload):
    gemini_output_raw_json: Optional[str] = None
    raw_llm_prompt: Optional[str] = None
    selected_photo_file_names: Optional[list[list[str]]] = []


class PostProcessUploadedAssetsInputPayload(JobInputPayload):
    asset_ids: list[UUID]


class PostProcessUploadedAssetsOutputPayload(JobOutputPayload):
    assets_rejected_invalid_mime: list[UUID]
    assets_post_process_failed: list[UUID]
    assets_post_process_succeeded: list[UUID]
