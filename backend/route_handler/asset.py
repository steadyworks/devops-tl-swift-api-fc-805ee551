import asyncio
import logging
import os
from typing import Optional
from uuid import UUID, uuid4

from fastapi import Request, WebSocket, WebSocketDisconnect, WebSocketException
from pydantic import BaseModel

from backend.db.dal import (
    DALAssets,
    DALPhotobooksAssetsRel,
    DAOAssetsCreate,
    DAOPhotobooksAssetsRelCreate,
    safe_commit,
)
from backend.db.data_models import AssetUploadStatus
from backend.lib.request.context import RequestContext
from backend.lib.utils.assets import (
    is_accepted_asset_ext_photos,
    is_accepted_mime,
)
from backend.lib.websocket.codec import WebSocketCodec
from backend.lib.websocket.registry import WebSocketRegistry
from backend.lib.websocket.types import (
    AssetUploadStatusMessage,
    AssetUploadStatusPayload,
)
from backend.route_handler.base import RouteHandler
from backend.worker.job_processor.types import (
    JobType,
    PostProcessUploadedAssetsInputPayload,
)

from .base import enforce_response_model


class AssetUploadFileInfo(BaseModel):
    client_file_index: int  # required for client-to-server upload mapping
    filename: str
    mime_type: Optional[str]


class AssetUploadSlot(BaseModel):
    client_file_index: int
    original_filename: str
    asset_id: UUID
    upload_url_put: str
    upload_url_get: str


class RejectedFile(BaseModel):
    client_file_index: int
    filename: str
    reason: str


class AssetUploadRequest(BaseModel):
    files: list[AssetUploadFileInfo]


class AssetUploadRequestResponse(BaseModel):
    accepted: list[AssetUploadSlot]
    rejected: list[RejectedFile]


class AssetAPIHandler(RouteHandler):
    def register_routes(self) -> None:
        self.route("/api/asset/request_uploads", "asset_request_uploads", ["POST"])
        self.websocket_route("/api/ws/asset/upload_status", "upload_status_ws")

    @enforce_response_model
    async def asset_request_uploads(
        self,
        request: Request,
        payload: AssetUploadRequest,
    ) -> AssetUploadRequestResponse:
        request_context = await self.get_request_context(request)
        owner_id = request_context.owner_id

        accepted: list[AssetUploadSlot] = []
        rejected: list[RejectedFile] = []
        asset_creates: list[DAOAssetsCreate] = []

        for file in payload.files:
            index = file.client_file_index
            filename = file.filename
            mime = file.mime_type
            ext = os.path.splitext(filename)[1]

            # ✅ Validate MIME type
            if not is_accepted_mime(mime):
                rejected.append(
                    RejectedFile(
                        client_file_index=index,
                        filename=filename,
                        reason="unsupported MIME type",
                    )
                )
                continue

            # ✅ Validate extension
            if not is_accepted_asset_ext_photos(ext):
                rejected.append(
                    RejectedFile(
                        client_file_index=index,
                        filename=filename,
                        reason="unsupported file extension",
                    )
                )
                continue

            # ✅ Generate S3 key + presigned URL
            asset_uuid = uuid4()
            asset_key_orig = self.app.asset_manager.mint_asset_key_for_presigned_slots(
                owner_id, f"{asset_uuid}{ext}"
            )
            # TODO: consider batching this if it becomes a bottleneck
            asset_upload_url_put, asset_upload_url_get = await asyncio.gather(
                self.app.asset_manager.generate_signed_url_put(asset_key_orig),
                self.app.asset_manager.generate_signed_url(asset_key_orig),
            )
            asset_creates.append(
                DAOAssetsCreate(
                    id=asset_uuid,
                    owner_id=owner_id,
                    asset_key_original=asset_key_orig,
                    upload_status=AssetUploadStatus.PENDING,
                )
            )
            accepted.append(
                AssetUploadSlot(
                    client_file_index=index,
                    asset_id=asset_uuid,
                    upload_url_put=asset_upload_url_put,
                    upload_url_get=asset_upload_url_get,
                    original_filename=filename,
                )
            )

        async with self.app.new_db_session() as db_session:
            async with safe_commit(
                db_session,
                context="initial assets creation DB write",
                raise_on_fail=True,
            ):
                await DALAssets.create_many(db_session, asset_creates)

        return AssetUploadRequestResponse(accepted=accepted, rejected=rejected)

    async def upload_status_ws(self, websocket: WebSocket) -> None:
        # Resolve owner_id from the socket (auth, cookies, headers, etc.)
        async with self.app.new_db_session() as db_session:
            try:
                request_context = await RequestContext.from_websocket(
                    websocket, db_session
                )
                owner_id = request_context.owner_id
            except WebSocketException as e:
                # Authentication/authorization failure → close and return
                await websocket.close(code=e.code)
                return

        # Accept socket and register
        await websocket.accept()
        await WebSocketRegistry.register(owner_id, websocket)
        logging.debug(f"[WS] Client connected for owner_id={owner_id}")

        codec = WebSocketCodec(websocket)

        try:
            # Keep the connection alive; ignore malformed frames (logged) and continue
            async for msg in codec.aiter_recv(
                log_prefix=f"[WS owner_id={owner_id}]",
                keepalive=True,
            ):
                try:
                    match msg:
                        case AssetUploadStatusMessage(payload=payload):
                            await self._handle_asset_upload_status_update(
                                owner_id, payload
                            )

                        case _:
                            # Shouldn't occur with a proper discriminated union, but log just in case
                            logging.warning(
                                f"[WS] Unknown event from owner_id={owner_id}: {getattr(msg, 'event', None)}"
                            )

                except Exception as e:
                    # Mirror your original "best-effort" loop with logging + continue
                    logging.warning(f"[WS] Failed to handle msg event, exception: {e}")
                    continue

        except WebSocketDisconnect:
            logging.info(f"[WS] WebSocket disconnected for owner_id={owner_id}")
        finally:
            await WebSocketRegistry.unregister(owner_id, websocket)

    async def _handle_asset_upload_status_update(
        self,
        owner_id: UUID,
        payload: AssetUploadStatusPayload,
    ) -> None:
        succeeded_ids: set[UUID] = set(payload.succeeded)
        failed_map: dict[UUID, str] = {
            entry.asset_id: entry.error_msg for entry in payload.failed
        }

        if not succeeded_ids and not failed_map:
            logging.debug(
                f"[WS] Empty upload status payload for owner_id={owner_id}, skipping"
            )
            return

        db_changed_rows_succeeded: list[UUID] = []
        async with self.app.new_db_session() as db_session:
            async with safe_commit(
                db_session,
                context="persist asset upload status",
                raise_on_fail=True,
            ):
                # Step 1: Mark successfully uploaded assets as SUCCEEDED (only if currently PENDING)
                if succeeded_ids:
                    db_changed_rows_succeeded = (
                        await DALAssets.bulk_update_status_where_pending(
                            session=db_session,
                            asset_ids=succeeded_ids,
                            owner_id=owner_id,
                            new_status=AssetUploadStatus.UPLOAD_SUCCEEDED,
                            current_matching_status=AssetUploadStatus.PENDING,
                        )
                    )
                    if payload.associated_photobook_id:
                        rels_to_create = [
                            DAOPhotobooksAssetsRelCreate(
                                photobook_id=payload.associated_photobook_id,
                                asset_id=asset_id,
                            )
                            for asset_id in db_changed_rows_succeeded
                        ]
                        if rels_to_create:
                            await DALPhotobooksAssetsRel.create_many(
                                db_session, rels_to_create
                            )
                    logging.info(
                        f"[WS] Marked {len(succeeded_ids)} assets as SUCCEEDED for owner_id={owner_id}"
                    )

                # Step 2: Mark failed uploads as FAILED_CLIENT_UPLOAD (only if currently PENDING)
                if failed_map:
                    failed_ids = set(failed_map.keys())
                    await DALAssets.bulk_update_status_where_pending(
                        session=db_session,
                        asset_ids=failed_ids,
                        owner_id=owner_id,
                        new_status=AssetUploadStatus.UPLOAD_FAILED,
                        current_matching_status=AssetUploadStatus.PENDING,
                    )
                    for asset_id, reason in failed_map.items():
                        logging.warning(
                            f"[WS] Asset {asset_id} failed to upload for owner_id={owner_id}: {reason}"
                        )

            # Enqueue asset background processing jobs
            if db_changed_rows_succeeded:
                await self.app.remote_job_manager_cpu_bound.enqueue(
                    JobType.REMOTE_POST_PROCESS_UPLOADED_ASSETS,
                    job_payload=PostProcessUploadedAssetsInputPayload(
                        owner_id=owner_id,
                        user_id=None,
                        asset_ids=db_changed_rows_succeeded,
                        originating_photobook_id=None,
                    ),
                    max_retries=2,
                    db_session=db_session,
                )
