from scripts.gpt_review import call_gpt_review


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_call_gpt_review_extracts_output_text():
    def fake_fetcher(url, headers, body):
        assert url == "https://api.openai.com/v1/responses"
        assert headers["Authorization"] == "Bearer test-key"
        assert body["model"] == "gpt-5.6-sol"
        assert "diff --git" in body["input"]
        return _FakeResp({
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "발견된 문제 없음"}],
                }
            ]
        })

    result = call_gpt_review("test-key", "diff --git a/x b/x\n+foo", fetcher=fake_fetcher)
    assert result == "발견된 문제 없음"


def test_call_gpt_review_raises_when_no_text_found():
    def fake_fetcher(url, headers, body):
        return _FakeResp({"output": []})

    try:
        call_gpt_review("test-key", "diff", fetcher=fake_fetcher)
        assert False, "should have raised"
    except RuntimeError:
        pass
