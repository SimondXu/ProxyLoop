from serving import config, liveness

IDS = [11, 22, 33, 44]


def body(model: str = "Qwen3.5-9B-zero") -> dict:
    return {"id": "cmpl-1", "model": model, "choices": [{"prompt_logprobs": [
        None,
        {"22": {"logprob": -1.0, "rank": 1}},
        {"33": {"logprob": -2.5, "rank": 3}, "7": {"logprob": -0.1, "rank": 1}},
        {"44": {"logprob": -0.25, "rank": 1}}]}]}


def test_prompt_logprobs_reads_the_actual_token_at_each_completion_position():
    assert liveness.prompt_logprobs(body(), IDS, start=2) == [-2.5, -0.25]


def test_read_response_requires_the_echoed_model():
    ok = liveness.read_response("Qwen3.5-9B-zero", 200, body(), IDS, 2)
    assert ok == {"status": 200, "server_id": "cmpl-1", "echoed_model": "Qwen3.5-9B-zero",
                  "logprobs": [-2.5, -0.25]}
    wrong = liveness.read_response("Qwen3.5-9B-zero", 200, body("Qwen3.5-9B"), IDS, 2)
    assert "echoed model" in wrong["error"] and "logprobs" not in wrong
    assert liveness.read_response("x", 404, None, IDS, 2) == {"status": 404, "error": "HTTP 404"}


def result(complete: bool, max_diff, mean_diff) -> dict:
    return {"complete": complete, "max_abs_diff": max_diff, "mean_abs_diff": mean_diff}


def test_verdicts():
    assert liveness.zero_ok(result(True, config.ZERO_MAX_DIFF, 0.0))
    assert not liveness.zero_ok(result(True, 2e-4, 1e-5))
    assert not liveness.zero_ok(result(False, None, None))
    assert liveness.live_ok(result(True, 0.5, 2e-3))
    assert not liveness.live_ok(result(True, 0.5, config.LIVE_MIN_MEAN_DIFF))
    assert not liveness.live_ok(result(False, None, None))
