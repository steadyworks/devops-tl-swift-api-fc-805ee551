import asyncio
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

from backend.db.dal import DALAssets, DAOAssetsUpdate, safe_commit
from backend.db.data_models import AssetUploadStatus
from backend.db.data_models.types import AssetMetadata, ExtractedExif
from backend.db.session.factory import AsyncSessionFactory
from backend.lib.asset_manager.base import AssetManager
from backend.lib.geo.radar_models import RadarReverseGeocodeResponse
from backend.lib.geo.radar_protocol import RadarHttpClientProtocol
from backend.lib.types.asset import Asset, AssetStorageKey
from backend.lib.utils.common import none_throws
from backend.lib.utils.web_requests import async_tempdir
from backend.worker.process.types import RemoteCPUBoundWorkerProcessResources

from .remote import RemoteJobProcessor
from .types import (
    PostProcessUploadedAssetsInputPayload,
    PostProcessUploadedAssetsOutputPayload,
)
from .utils.compress_upload_mixin import AssetKeyType, CompressUploadMixin
from .utils.file_encoder import encode_files_to_data_urls
from .utils.types import CompressionTier
from .utils.vips import ImageProcessingLibrary, ImageProcessingResult

MIN_FREE_DISK_BYTES = 100 * 1024 * 1024  # 100MB


async def batch_reverse_geocode(
    exif_map: dict[Path, Optional[ExtractedExif]],
    radar_client: RadarHttpClientProtocol,
) -> dict[Path, Optional[RadarReverseGeocodeResponse]]:
    """Batch reverse geocode all valid paths using their EXIF GPS data."""

    async def reverse_one(
        path: Path, lat: float, lng: float
    ) -> tuple[Path, Optional[RadarReverseGeocodeResponse]]:
        try:
            result = await radar_client.reverse_geocode(lat, lng)
            return path, result
        except Exception as e:
            logging.warning(f"[radar] Reverse geocode failed for {path}: {e}")
            return path, None

    tasks: list[asyncio.Task[tuple[Path, Optional[RadarReverseGeocodeResponse]]]] = []

    for path, exif in exif_map.items():
        if not exif or exif.gps_latitude is None or exif.gps_longitude is None:
            continue
        tasks.append(
            asyncio.create_task(
                reverse_one(path, exif.gps_latitude, exif.gps_longitude)
            )
        )

    results: dict[Path, Optional[RadarReverseGeocodeResponse]] = {}
    for coro in asyncio.as_completed(tasks):
        path, result = await coro
        results[path] = result

    return results


class RemotePostProcessUploadedAssetsJobProcessor(
    RemoteJobProcessor[
        PostProcessUploadedAssetsInputPayload,
        PostProcessUploadedAssetsOutputPayload,
        RemoteCPUBoundWorkerProcessResources,
    ],
    CompressUploadMixin,
):
    def __init__(
        self,
        job_id: UUID,
        asset_manager: AssetManager,
        db_session_factory: AsyncSessionFactory,
        worker_process_resources: RemoteCPUBoundWorkerProcessResources,
    ) -> None:
        super().__init__(
            job_id,
            asset_manager,
            db_session_factory,
            worker_process_resources,
        )
        self._image_lib = ImageProcessingLibrary(
            max_concurrent=1,
        )

    async def process(
        self, input_payload: PostProcessUploadedAssetsInputPayload
    ) -> PostProcessUploadedAssetsOutputPayload:
        compress_upload_succeeded_uuids: list[UUID] = []
        compress_upload_failed_uuids: list[UUID] = []
        rejected_mime_uuids: list[UUID] = []  # FIXME

        async with async_tempdir() as root_dir:
            try:
                should_abort, error_message = self._sanity_check_free_storage(root_dir)
                if should_abort:
                    raise Exception(error_message)

                # Mark as begin processing
                async with self.db_session_factory.new_session() as db_session:
                    async with safe_commit(
                        db_session,
                        context="processing status DB update",
                        raise_on_fail=False,
                    ):
                        await DALAssets.update_many_by_ids(
                            db_session,
                            {
                                asset_id: DAOAssetsUpdate(
                                    upload_status=AssetUploadStatus.PROCESSING,
                                )
                                for asset_id in input_payload.asset_ids
                            },
                        )

                    asset_daos = await DALAssets.get_by_ids(
                        db_session, input_payload.asset_ids
                    )

                # Begin compressing
                asset_uuid_orig_key_map: dict[UUID, AssetStorageKey] = {
                    dao.id: none_throws(dao.asset_key_original) for dao in asset_daos
                }
                orig_keys_asset_uuid_map: dict[AssetStorageKey, UUID] = {
                    v: k for k, v in asset_uuid_orig_key_map.items()
                }
                download_results: dict[
                    AssetStorageKey, Asset | Exception
                ] = await self.asset_manager.download_files_batched(
                    [
                        (key, root_dir / Path(key).name)
                        for key in asset_uuid_orig_key_map.values()
                    ]
                )

                # original path -> UUID
                media_paths_asset_uuids_map: dict[Path, UUID] = {
                    none_throws(asset.cached_local_path): orig_keys_asset_uuid_map[
                        storage_key
                    ]
                    for storage_key, asset in download_results.items()
                    if isinstance(asset, Asset)
                }

                # orig path -> (success, compressed path)
                compressed_result_highend_display: dict[
                    Path, ImageProcessingResult
                ] = await self._image_lib.compress_by_tier_on_thread(
                    input_paths=list(media_paths_asset_uuids_map.keys()),
                    output_dir=root_dir,
                    format="jpeg",
                    tier=CompressionTier.HIGH_END_DISPLAY,
                    strip_metadata=False,
                )
                # orig path -> (success, compressed path)
                compressed_result_llm: dict[
                    Path, ImageProcessingResult
                ] = await self._image_lib.compress_by_tier_from_compressed_on_thread(
                    input_path_compressed_path_map={
                        orig_path: (
                            compressed_result.compressed_path
                            if compressed_result.is_compress_succeeded
                            else orig_path
                        )
                        for orig_path, compressed_result in compressed_result_highend_display.items()
                    },
                    output_dir=root_dir,
                    format="jpeg",
                    tier=CompressionTier.LLM,
                    strip_metadata=False,
                )

                compressed_result_thumbnail: dict[
                    Path, ImageProcessingResult
                ] = await self._image_lib.compress_by_tier_from_compressed_on_thread(
                    input_path_compressed_path_map={
                        orig_path: (
                            compressed_result.compressed_path
                            if compressed_result.is_compress_succeeded
                            else orig_path
                        )
                        for orig_path, compressed_result in compressed_result_llm.items()
                    },
                    output_dir=root_dir,
                    format="jpeg",
                    tier=CompressionTier.THUMBNAIL,
                    strip_metadata=True,
                )

                # orig path -> (success, compressed path)
                compressed_result_placeholder_blur: dict[
                    Path, ImageProcessingResult
                ] = await self._image_lib.compress_by_tier_from_compressed_on_thread(
                    input_path_compressed_path_map={
                        orig_path: (
                            compressed_result.compressed_path
                            if compressed_result.is_compress_succeeded
                            else orig_path
                        )
                        for orig_path, compressed_result in compressed_result_llm.items()
                    },
                    output_dir=root_dir,
                    format="jpeg",
                    tier=CompressionTier.PLACEHOLDER_BLUR,
                    strip_metadata=True,
                )
                succeeded_compressed_path_placeholder_blur_original_path_map: dict[
                    Path, Path
                ] = dict()
                for (
                    orig_path,
                    compression_result,
                ) in compressed_result_placeholder_blur.items():
                    if compression_result.is_compress_succeeded:
                        succeeded_compressed_path_placeholder_blur_original_path_map[
                            none_throws(compression_result.compressed_path)
                        ] = orig_path
                encoded_compressed_paths = await encode_files_to_data_urls(
                    list(
                        succeeded_compressed_path_placeholder_blur_original_path_map.keys()
                    )
                )

                # compressed path -> (compressed asset key, orig path, tier)
                succeeded_compressed_path_asset_keys_map: dict[
                    Path, tuple[AssetStorageKey, Path, AssetKeyType]
                ] = dict()

                compressed_results_in_tiers: list[
                    tuple[dict[Path, ImageProcessingResult], AssetKeyType]
                ] = [
                    (compressed_result_thumbnail, "asset_key_thumbnail"),
                    (compressed_result_llm, "asset_key_llm"),
                    (compressed_result_highend_display, "asset_key_display"),
                ]

                for res, tier in compressed_results_in_tiers:
                    for orig_path, image_processing_result in res.items():
                        if not image_processing_result.is_compress_succeeded:
                            continue

                        compressed_path = none_throws(
                            image_processing_result.compressed_path
                        )
                        succeeded_compressed_path_asset_keys_map[compressed_path] = (
                            self.asset_manager.mint_asset_key_for_presigned_slots(
                                input_payload.owner_id, compressed_path.name
                            ),
                            orig_path,
                            tier,
                        )

                # Aggregate exif results: original path -> exif
                original_path_exif_map: dict[Path, Optional[ExtractedExif]] = dict()
                for original_path in compressed_result_llm:
                    original_path_exif_map[original_path] = (
                        compressed_result_llm[original_path].exif_result
                        or compressed_result_highend_display[original_path].exif_result
                    )

                # Kick off both upload and geocode tasks concurrently
                upload_task = asyncio.create_task(
                    self.asset_manager.upload_files_batched(
                        [
                            (compressed_path, compressed_asset_key)
                            for compressed_path, (
                                compressed_asset_key,
                                _,
                                _,
                            ) in succeeded_compressed_path_asset_keys_map.items()
                        ]
                    )
                )

                geocode_task = asyncio.create_task(
                    batch_reverse_geocode(
                        original_path_exif_map,
                        self.worker_process_resources.radar_client,
                    )
                )

                # Step 1: Await the critical upload task
                upload_result_or_exc = await upload_task

                # Step 2: Give geocode task a 2-second grace period after upload completes
                radar_result_or_exc: Optional[
                    dict[Path, RadarReverseGeocodeResponse | None] | BaseException
                ] = None
                try:
                    radar_result_or_exc = await asyncio.wait_for(
                        geocode_task, timeout=2.0
                    )
                except asyncio.TimeoutError:
                    logging.warning(
                        "[radar] Geocode task did not finish in 2s after upload. Cancelling."
                    )
                    geocode_task.cancel()
                    try:
                        await geocode_task
                    except asyncio.CancelledError:
                        radar_result_or_exc = None
                        logging.info("[radar] Geocode task cancelled cleanly.")
                    except BaseException as e:
                        radar_result_or_exc = e  # capture unexpected failure
                        logging.error(
                            f"[radar] Geocode task failed after cancellation: {e}"
                        )

                # Handle geocoding result. Swallow failure as non-critical
                radar_results: dict[Path, Optional[RadarReverseGeocodeResponse]] = (
                    dict()
                )
                if isinstance(radar_result_or_exc, dict):
                    radar_results = radar_result_or_exc

                # Handle upload result. Raise as this is critical failure
                if isinstance(upload_result_or_exc, BaseException):
                    raise upload_result_or_exc
                upload_results = upload_result_or_exc
                succeeded_uploaded_compressed_paths = [
                    p for p in upload_results if isinstance(upload_results[p], Asset)
                ]

                # Aggregate results and write to DB
                writes: dict[UUID, DAOAssetsUpdate] = dict()
                for compressed_path in succeeded_uploaded_compressed_paths:
                    (compressed_asset_key, original_path, tier) = (
                        succeeded_compressed_path_asset_keys_map[compressed_path]
                    )
                    uuid = media_paths_asset_uuids_map[original_path]
                    if uuid not in writes:
                        writes[uuid] = DAOAssetsUpdate()

                    if tier == "asset_key_display":
                        writes[uuid].asset_key_display = compressed_asset_key
                    elif tier == "asset_key_llm":
                        writes[uuid].asset_key_llm = compressed_asset_key
                    elif tier == "asset_key_thumbnail":
                        writes[uuid].asset_key_thumbnail = compressed_asset_key
                    else:
                        raise Exception("Invalid compression tier specified")

                    exif = original_path_exif_map[original_path]
                    if exif is not None:
                        writes[uuid].exif = exif.model_dump(mode="json")

                    geo_result = radar_results.get(original_path, None)
                    if geo_result and geo_result.meta.code == 200:
                        if addresses := geo_result.addresses:
                            address = addresses[0]
                            writes[uuid].metadata_json = AssetMetadata(
                                exif_radar_formatted_address=address.formattedAddress,
                                exif_radar_place_label=address.placeLabel,
                                exif_radar_state_code=address.stateCode,
                                exif_radar_country_code=address.countryCode,
                            ).model_dump(mode="json")

                for (
                    compressed_path_placeholder_blur,
                    encoded_data_url,
                ) in encoded_compressed_paths.items():
                    if encoded_data_url is not None:
                        writes[
                            media_paths_asset_uuids_map[
                                succeeded_compressed_path_placeholder_blur_original_path_map[
                                    compressed_path_placeholder_blur
                                ]
                            ]
                        ].blur_data_url = encoded_data_url

                for uuid, dao in writes.items():
                    if (
                        dao.asset_key_display is not None
                        and dao.asset_key_llm is not None
                        and dao.asset_key_thumbnail is not None
                    ):
                        dao.upload_status = AssetUploadStatus.READY
                        compress_upload_succeeded_uuids.append(uuid)
                    else:
                        dao.upload_status = AssetUploadStatus.PROCESSING_FAILED
                        compress_upload_failed_uuids.append(uuid)

                for uuid in asset_uuid_orig_key_map.keys():
                    if uuid not in writes:
                        writes[uuid] = DAOAssetsUpdate(
                            upload_status=AssetUploadStatus.PROCESSING_FAILED
                        )
                        compress_upload_failed_uuids.append(uuid)

                async with self.db_session_factory.new_session() as db_session:
                    async with safe_commit(
                        db_session,
                        context="persisting processed asset keys",
                        raise_on_fail=True,
                    ):
                        await DALAssets.update_many_by_ids(
                            db_session,
                            writes,
                        )

            except Exception as e:
                async with self.db_session_factory.new_session() as db_session:
                    async with safe_commit(
                        db_session,
                        context="upload failed status DB update",
                        raise_on_fail=False,
                    ):
                        await DALAssets.update_many_by_ids(
                            db_session,
                            {
                                asset_id: DAOAssetsUpdate(
                                    upload_status=AssetUploadStatus.PROCESSING_FAILED,
                                )
                                for asset_id in input_payload.asset_ids
                            },
                        )
                raise e

        return PostProcessUploadedAssetsOutputPayload(
            job_id=self.job_id,
            assets_post_process_succeeded=compress_upload_succeeded_uuids,
            assets_post_process_failed=compress_upload_failed_uuids,
            assets_rejected_invalid_mime=rejected_mime_uuids,
        )
