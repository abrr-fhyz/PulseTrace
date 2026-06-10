from unittest.mock import patch, MagicMock
from lib.llm import chat_json


def _mock_response(text: str):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=text))])


def test_chat_json_parses():
    with patch("lib.llm.OpenAI") as O:
        O.return_value.chat.completions.create.return_value = _mock_response('{"a": 1}')
        assert chat_json("s", "u") == {"a": 1}


def test_chat_json_retries_then_succeeds():
    with patch("lib.llm.OpenAI") as O:
        O.return_value.chat.completions.create.side_effect = [
            _mock_response("not json"),
            _mock_response('{"ok": true}'),
        ]
        assert chat_json("s", "u") == {"ok": True}


def test_chat_json_salvages_json_wrapped_in_prose():
    with patch("lib.llm.OpenAI") as O:
        O.return_value.chat.completions.create.return_value = _mock_response(
            'Sure, here is the analysis you asked for:\n{"verdict": "mixed"}\nHope that helps!'
        )
        assert chat_json("s", "u") == {"verdict": "mixed"}


def test_chat_json_empty_content_yields_empty_dict():
    with patch("lib.llm.OpenAI") as O:
        O.return_value.chat.completions.create.return_value = _mock_response("")
        assert chat_json("s", "u") == {}
