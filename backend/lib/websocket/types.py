from enum import Enum
from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

from backend.db.data_models import (
    PhotobookStatus,
)

# ---- WebSocket Event Types ----


class ClientToServerWebSocketEventType(str, Enum):
    # Client → Server
    ASSET_UPLOAD_STATUS_UPDATE = "asset_upload_status_update"
    PHOTOBOOK_STATUS_SUBSCRIBE = "photobook_status_subscribe"


class ServerToClientWebSocketEventType(str, Enum):
    # Server → Client
    ASSET_REJECTED_INVALID_MIME = "asset_rejected_invalid_mime"
    ASSET_REJECTED_CORRUPT = "asset_rejected_corrupt"
    ASSET_FAILED_PERMANENTLY = "asset_failed_permanently"

    PHOTOBOOK_STATUS_UPDATE = "photobook_status_update"
    PHOTOBOOK_STATUS_ERROR = "photobook_status_error"


################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################


# ---- Client → Server Payloads ----
class PhotobookStatusSubscribePayload(BaseModel):
    photobook_id: UUID


class PhotobookStatusSubscribeMessage(BaseModel):
    event: Literal[ClientToServerWebSocketEventType.PHOTOBOOK_STATUS_SUBSCRIBE]
    payload: PhotobookStatusSubscribePayload


class AssetUploadStatusFailed(BaseModel):
    asset_id: UUID
    error_msg: str


class AssetUploadStatusPayload(BaseModel):
    associated_photobook_id: Optional[UUID] = None
    succeeded: list[UUID]
    failed: list[AssetUploadStatusFailed]


class AssetUploadStatusMessage(BaseModel):
    event: Literal[ClientToServerWebSocketEventType.ASSET_UPLOAD_STATUS_UPDATE]
    payload: AssetUploadStatusPayload


# ---- Discriminated union (key = "event") ----
ClientToServerMessage = Annotated[
    Union[AssetUploadStatusMessage, PhotobookStatusSubscribeMessage],
    Field(discriminator="event"),
]

# For fast validation
ClientToServerAdapter: TypeAdapter[ClientToServerMessage] = TypeAdapter(
    ClientToServerMessage
)


################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################
################################################################################


# ---- Server → Client Payloads ----
class AssetRejectedInvalidMIMEPayload(BaseModel):
    image_id: UUID
    message: str = "Unsupported MIME type"


class AssetRejectedCorruptPayload(BaseModel):
    image_id: UUID
    message: str = "Corrupt or unreadable image file"


class AssetFailedPermanentlyPayload(BaseModel):
    image_id: UUID
    message: str
    retryable: bool = False


class PhotobookStatusUpdatePayload(BaseModel):
    photobook_id: UUID
    status: Optional[PhotobookStatus]


class PhotobookStatusErrorPayload(BaseModel):
    photobook_id: Optional[UUID] = None
    message: str


# ---- Server → Client Envelopes ----


class AssetRejectedInvalidMIMEMessage(BaseModel):
    event: Literal[ServerToClientWebSocketEventType.ASSET_REJECTED_INVALID_MIME]
    payload: AssetRejectedInvalidMIMEPayload


class AssetRejectedCorruptMessage(BaseModel):
    event: Literal[ServerToClientWebSocketEventType.ASSET_REJECTED_CORRUPT]
    payload: AssetRejectedCorruptPayload


class AssetFailedPermanentlyMessage(BaseModel):
    event: Literal[ServerToClientWebSocketEventType.ASSET_FAILED_PERMANENTLY]
    payload: AssetFailedPermanentlyPayload


class PhotobookStatusUpdateMessage(BaseModel):
    event: Literal[ServerToClientWebSocketEventType.PHOTOBOOK_STATUS_UPDATE]
    payload: PhotobookStatusUpdatePayload


class PhotobookStatusErrorMessage(BaseModel):
    event: Literal[ServerToClientWebSocketEventType.PHOTOBOOK_STATUS_ERROR]
    payload: PhotobookStatusErrorPayload


# ---- Discriminated union (key = "event") ----
ServerToClientMessage = Annotated[
    Union[
        AssetRejectedInvalidMIMEMessage,
        AssetRejectedCorruptMessage,
        AssetFailedPermanentlyMessage,
        PhotobookStatusUpdateMessage,
        PhotobookStatusErrorMessage,
    ],
    Field(discriminator="event"),
]

# For fast validation
ServerToClientAdapter: TypeAdapter[ServerToClientMessage] = TypeAdapter(
    ServerToClientMessage
)
