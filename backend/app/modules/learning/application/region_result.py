"""The result of one study region: what the learner did there, read back from the learning log.

Nothing here is stored or scored: it sums the learner's own log rows whose source is this region.
"""
from uuid import UUID

from app.kernel.region_ids import split_region_id
from app.modules.activity.contracts import RegionResult, region_result
from app.modules.learning.application.practice_log import PracticeLogError


class RegionResultService:
    def __init__(self, *, library, activity):
        self.library = library
        self.activity = activity

    def result(self, user, library_item_id: UUID, region: str) -> RegionResult:
        if self.library.get_for_user(library_item_id=library_item_id, user_id=user.id) is None:
            raise PracticeLogError(404, "library_item_not_found", "Library item not found.")
        if split_region_id(region) is None:
            raise PracticeLogError(422, "region_invalid", "That part is not valid.")
        return region_result(region, self.activity.for_source(user.id, source_type="video_region", source_id=region))
