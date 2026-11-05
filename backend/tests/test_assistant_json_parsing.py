"""Model-output compatibility and safety tests for assistant JSON."""
import json
from unittest.mock import MagicMock, patch

import pytest

from app.services import assistant_prompts, llm


@pytest.mark.parametrize("output, expected", [
    ('```json\n{"kind":"later"}\n```', {"kind": "later"}),
    ('<think>不要读取 {"kind":"notice"}</think>结果：{"kind":"later"}', {"kind": "later"}),
    ('说明 {"text":"字符串里的 } 和 ,]", "items":[1,2,], "ok":true,}',
     {"text": "字符串里的 } 和 ,]", "items": [1, 2], "ok": True}),
    ("{'same_event': False, 'thread_id': None,}", {"same_event": False, "thread_id": None}),
    ('提示 {不是对象} 最终结果 {"title":"有效"}', {"title": "有效"}),
])
def test_parse_model_outputs(output, expected):
    assert llm._parse_json(output) == expected


@pytest.mark.parametrize("output", [
    '<think>仍在思考 {"kind":"later"}',
    '{"outer":{"title":"不完整"}',
    '{"title": "截断',
    '没有 JSON',
    '{"value": NaN}',
])
def test_reject_incomplete_or_invalid_outputs(output):
    with pytest.raises(ValueError):
        llm._parse_json(output)


def test_required_fields_retry_with_original_images():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}
    messages = [{"role": "user", "content": [{"type": "text", "text": "整理"}, image]}]
    with patch.object(llm, "chat", side_effect=['{"reason":"缺字段"}', '{"kind":"notice"}']) as chat:
        assert llm.chat_structured(messages, required_keys=("kind",)) == {"kind": "notice"}
    assert image in chat.call_args.args[0][1]["content"]


def test_assistant_structured_output_budget_is_100k():
    with patch.object(llm, "chat", return_value='{"kind":"notice"}') as chat:
        assert llm.chat_structured([{"role": "user", "content": "测试"}], required_keys=("kind",))["kind"] == "notice"
    assert chat.call_args.kwargs["max_tokens"] == 100000


def test_failure_reports_missing_final_answer_without_echoing_private_text():
    with patch.object(llm, "chat", return_value=""):
        with pytest.raises(llm.AiUnavailable, match="没有返回最终答案") as exc:
            llm.chat_structured([{"role": "user", "content": "私密邮件内容"}])
    assert "私密邮件内容" not in str(exc.value)


def test_examples_in_each_chinese_prompt_are_valid_json():
    for prompt in (assistant_prompts.CLASSIFY_PROMPT, assistant_prompts.NOTICE_PROMPT,
                   assistant_prompts.CANDIDATE_PROMPT, assistant_prompts.RECONCILE_PROMPT,
                   assistant_prompts.LATER_PROMPT):
        assert json.loads(prompt.splitlines()[-1])


def test_openai_compatible_text_parts_are_combined():
    resp = MagicMock()
    resp.__enter__.return_value = resp
    resp.read.return_value = json.dumps({"choices": [{"message": {"content": [
        {"type": "text", "text": "{\"kind\":"}, {"type": "text", "text": "\"later\"}"}
    ]}}]}).encode()
    with patch("urllib.request.urlopen", return_value=resp):
        result = llm._do_request({"endpoint": "http://localhost:1/v1", "model": "test", "timeout": 1}, [], 100, 0)
    assert json.loads(result) == {"kind": "later"}
