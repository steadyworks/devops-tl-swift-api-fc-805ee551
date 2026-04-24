import logging
import random
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from backend.db.dal import (
    DALAssets,
    DALPages,
    DALPagesAssetsRel,
    DALPhotobooks,
    DAOPagesAssetsRelCreate,
    DAOPagesCreate,
    DAOPhotobooksUpdate,
)
from backend.db.dal.base import safe_commit
from backend.db.data_models import PhotobookStatus, UserProvidedOccasion
from backend.db.data_models.types import PageSchema, PhotobookSchema
from backend.db.session.factory import AsyncSessionFactory
from backend.db.utils.common import retrieve_available_asset_key_in_order_of
from backend.lib.asset_manager.base import AssetManager
from backend.lib.utils.common import none_throws
from backend.lib.utils.retryable import retryable_with_backoff
from backend.lib.vertex_ai.gemini import (
    Gemini,
    RawLLMPrompt,
    SelectedPhotoFileNames,
)
from backend.worker.process.types import RemoteIOBoundWorkerProcessResources

from .remote import RemoteJobProcessor
from .types import PhotobookGenerationInputPayload, PhotobookGenerationOutputPayload

if TYPE_CHECKING:
    from backend.lib.types.asset import AssetStorageKey


class RemotePhotobookGenerationJobProcessor(
    RemoteJobProcessor[
        PhotobookGenerationInputPayload,
        PhotobookGenerationOutputPayload,
        RemoteIOBoundWorkerProcessResources,
    ]
):
    def __init__(
        self,
        job_id: UUID,
        asset_manager: AssetManager,
        db_session_factory: AsyncSessionFactory,
        worker_process_resources: RemoteIOBoundWorkerProcessResources,
    ) -> None:
        super().__init__(
            job_id, asset_manager, db_session_factory, worker_process_resources
        )
        self.gemini = Gemini()

    def _randomized_page_message_options(
        self,
        photobook: PhotobookSchema,
    ) -> PhotobookSchema:
        pages_message_options_randomized: list[PageSchema] = []
        for page in photobook.photobook_pages:
            message_options = [page.page_message] + page.page_message_alternatives
            if len(message_options) > 2:
                take_i_th_option = random.randint(
                    0, 2
                )  # Randomly select one from the top-3 options
            else:
                take_i_th_option = 0

            pages_message_options_randomized.append(
                PageSchema(
                    page_photos=page.page_photos,
                    page_message=message_options[take_i_th_option],
                    page_message_alternatives=[
                        message_options[i]
                        for i in range(len(message_options))
                        if i != take_i_th_option
                    ],
                )
            )
        return PhotobookSchema(
            photobook_title=photobook.photobook_title,
            photobook_pages=pages_message_options_randomized,
            overall_gift_message=photobook.overall_gift_message,
            overall_gift_message_alternatives=photobook.overall_gift_message_alternatives,
        )

    async def process(
        self, input_payload: PhotobookGenerationInputPayload
    ) -> PhotobookGenerationOutputPayload:
        asset_ids = input_payload.asset_ids
        logging.info(
            f"[job-processor] Processing job {self.job_id} created from photobook: "
            f"{none_throws(input_payload.originating_photobook_id)}"
        )
        async with self.db_session_factory.new_session() as db_session:
            asset_objs = await DALAssets.get_by_ids(db_session, asset_ids)
            asset_uuid_dao_obj_maps = {dao.id: dao for dao in asset_objs}
            asset_uuid_asset_key_map = {
                obj.id: retrieve_available_asset_key_in_order_of(
                    obj, ["asset_key_llm", "asset_key_display", "asset_key_original"]
                )
                for obj in asset_objs
            }
            originating_photobook = none_throws(
                await DALPhotobooks.get_by_id(
                    db_session, none_throws(input_payload.originating_photobook_id)
                ),
                f"originating_photobook: {none_throws(input_payload.originating_photobook_id)} not found",
            )

        gemini_output = None
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            logging.info(
                f"[job-processor] Downloading files from asset storage: "
                f"{asset_uuid_asset_key_map}"
            )

            # asset key -> cached asset
            download_results = await self.asset_manager.download_files_batched(
                [
                    (key, tmp_path / Path(key).name)
                    for key in asset_uuid_asset_key_map.values()
                ]
            )

            failed_keys: dict[AssetStorageKey, Exception] = dict()
            downloaded_paths_exifs_and_metadata: dict[
                UUID, tuple[Path, Optional[dict[str, Any]], Optional[dict[str, Any]]]
            ] = dict()

            for asset_uuid, asset_key in asset_uuid_asset_key_map.items():
                download_result = download_results[asset_key]
                if isinstance(download_result, Exception):
                    failed_keys[asset_key] = download_result
                else:
                    downloaded_paths_exifs_and_metadata[asset_uuid] = (
                        none_throws(download_result.cached_local_path),
                        asset_uuid_dao_obj_maps[asset_uuid].exif,
                        asset_uuid_dao_obj_maps[asset_uuid].metadata_json,
                    )

            if failed_keys:
                logging.warning(f"[job-processor] Failed downloads: {failed_keys}")
            if not downloaded_paths_exifs_and_metadata:
                raise RuntimeError("All image downloads failed")

            img_filename_assets_map = {
                Path(asset_uuid_asset_key_map[asset.id]).name: asset
                for asset in asset_objs
            }

            logging.info(
                f"[job-processor] Running gemini for job {input_payload.originating_photobook_id}"
            )
            try:

                async def run_job_with_retry(
                    paths_and_exifs: list[
                        tuple[Path, Optional[dict[str, Any]], Optional[dict[str, Any]]]
                    ],
                    occasion: Optional[UserProvidedOccasion],
                    custom_details: Optional[str],
                    context: Optional[str],
                    gift_recipient: Optional[str],
                ) -> tuple[PhotobookSchema, RawLLMPrompt, SelectedPhotoFileNames]:
                    return await self.gemini.run_image_understanding_job(
                        paths_and_exifs,
                        occasion,
                        custom_details,
                        context,
                        gift_recipient,
                    )

                (
                    gemini_output,
                    raw_llm_prompt,
                    selected_photo_file_names,
                ) = await retryable_with_backoff(
                    coro_factory=lambda: run_job_with_retry(
                        list(downloaded_paths_exifs_and_metadata.values()),
                        originating_photobook.user_provided_occasion,
                        originating_photobook.user_provided_occasion_custom_details,
                        originating_photobook.user_provided_context,
                        originating_photobook.user_gift_recipient,
                    ),
                    retryable=(Exception,),
                    max_attempts=3,
                    base_delay=0.5,
                )
            except Exception as e:
                logging.exception("[job-processor] Gemini call failed")
                raise RuntimeError(
                    f"Gemini call fail. Book ID: {originating_photobook.id}. "
                    f"gemini_output: {gemini_output}. Exception: {e}"
                ) from e

        gemini_output = self._randomized_page_message_options(gemini_output)

        async with self.db_session_factory.new_session() as db_session:
            async with safe_commit(
                db_session,
                context="persisting photobook and pages, finalizing photobook creation",
                raise_on_fail=True,
            ):
                page_create_objs = [
                    DAOPagesCreate(
                        photobook_id=originating_photobook.id,
                        revision=1,
                        page_number=idx,
                        layout=None,
                        user_message=page_schema.page_message.message,
                        user_message_alternative_options=page_schema.serialize_page_message_alternatives(
                            page_schema.page_message_alternatives
                        ),
                        user_message_alternative_options_outdated=False,
                    )
                    for idx, page_schema in enumerate(gemini_output.photobook_pages)
                ]
                pages = await DALPages.create_many(db_session, page_create_objs)

                first_asset_id: Optional[UUID] = None
                pages_assets_rel_creates: list[DAOPagesAssetsRelCreate] = []
                for page_schema, page in zip(gemini_output.photobook_pages, pages):
                    for idx, page_photo in enumerate(page_schema.page_photos):
                        asset_nullable = img_filename_assets_map.get(page_photo, None)
                        if asset_nullable is not None:
                            pages_assets_rel_creates.append(
                                DAOPagesAssetsRelCreate(
                                    page_id=page.id,
                                    asset_id=asset_nullable.id,
                                    order_index=idx,
                                    caption=None,
                                )
                            )
                            if first_asset_id is None:
                                first_asset_id = asset_nullable.id

                await DALPagesAssetsRel.create_many(
                    db_session, pages_assets_rel_creates
                )
                await DALPhotobooks.update_by_id(
                    db_session,
                    originating_photobook.id,
                    DAOPhotobooksUpdate(
                        status=PhotobookStatus.DRAFT,
                        title=gemini_output.photobook_title,
                        thumbnail_asset_id=None
                        if first_asset_id is None
                        else first_asset_id,
                        suggested_overall_gift_message=gemini_output.overall_gift_message.message,
                        suggested_overall_gift_message_tone=gemini_output.overall_gift_message.tone,
                        suggested_overall_gift_message_alternative_options=gemini_output.serialize_overall_gift_message_alternatives(
                            gemini_output.overall_gift_message_alternatives
                        ),
                    ),
                )

        return PhotobookGenerationOutputPayload(
            job_id=self.job_id,
            gemini_output_raw_json=gemini_output.model_dump_json(),
            raw_llm_prompt=raw_llm_prompt,
            selected_photo_file_names=selected_photo_file_names,
        )
