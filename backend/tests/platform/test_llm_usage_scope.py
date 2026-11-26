"""M1 S7: LLM usage lines name the region or Library item they are spent on."""
import logging
from types import SimpleNamespace
from uuid import uuid4

from app.platform.llm import openai_compatible
from app.platform.llm.usage import current_usage_scope, usage_scope


def _usage_line(caplog) -> str:
    response = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=2,
                                                     completion_tokens_details=None))
    provider = SimpleNamespace(provider_name="p", model_name="m")
    with caplog.at_level(logging.INFO, logger=openai_compatible.logger.name):
        openai_compatible._log_usage(response, provider=provider, response_model=SimpleNamespace(__name__="R"))
    return [record.getMessage() for record in caplog.records if "llm_usage" in record.getMessage()][-1]


def test_usage_outside_a_scope_is_logged_as_none_with_a_utc_time(caplog):
    line = _usage_line(caplog)
    assert " scope=none at=" in line and line.endswith("Z")


def test_scopes_nest_and_reset(caplog):
    region, item = uuid4(), uuid4()
    with usage_scope("region_preparation", region):
        assert current_usage_scope() == f"region_preparation:{region}"
        with usage_scope("companion", item):
            assert f"scope=companion:{item} " in _usage_line(caplog)
        assert current_usage_scope() == f"region_preparation:{region}"
    assert current_usage_scope() == "none"
    with usage_scope("companion", None):
        assert current_usage_scope() == "companion:none"


def test_companion_model_calls_are_scoped_to_the_video(caplog):
    from tests.learning.test_companion import ITEM_ID, USER, make_service
    from app.modules.learning.domain.companion import CompanionEntry
    service = make_service()
    seen = []
    original = service.model.generate_with_tools

    def spy(*args, **kwargs):
        seen.append(current_usage_scope())
        return original(*args, **kwargs)

    service.model.generate_with_tools = spy
    service.start(USER, CompanionEntry.VIDEO, ITEM_ID)
    assert seen and set(seen) == {f"companion:{ITEM_ID}"}
