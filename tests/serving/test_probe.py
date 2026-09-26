import json

import pytest

from serving import probe


def record() -> dict:
    return {"server_id": None, "ttft_s": None, "ttfs_s": None, "prompt_tokens": None,
            "completion_tokens": None, "text": "", "error": None}


def sse(obj) -> str:
    return "data: " + json.dumps(obj)


def chunk(text: str) -> str:
    return sse({"id": "cmpl-pl-probe-1", "choices": [{"index": 0, "text": text}]})


def test_absorb_times_first_token_and_first_sentence():
    r = record()
    probe.absorb(r, ": keep-alive", 0.01)
    probe.absorb(r, chunk(""), 0.05)
    assert r["ttft_s"] is None
    probe.absorb(r, chunk("Sure"), 0.10)
    probe.absorb(r, chunk(", the total is 3.5"), 0.20)  # a decimal point is not a sentence end
    assert (r["ttft_s"], r["ttfs_s"]) == (0.10, None)
    probe.absorb(r, chunk(" dollars. Anything"), 0.30)
    probe.absorb(r, chunk(" else?"), 0.40)
    probe.absorb(r, sse({"id": "cmpl-pl-probe-1", "choices": [],
                         "usage": {"prompt_tokens": 1500, "completion_tokens": 9}}), 0.41)
    probe.absorb(r, "data: [DONE]", 0.42)
    assert (r["ttft_s"], r["ttfs_s"]) == (0.10, 0.30)
    assert r["text"] == "Sure, the total is 3.5 dollars. Anything else?"
    assert r["server_id"] == "cmpl-pl-probe-1"
    assert (r["prompt_tokens"], r["completion_tokens"]) == (1500, 9)
    assert r["error"] is None


def test_sentence_end_at_stream_end_counts():
    r = record()
    probe.absorb(r, chunk("Done."), 0.2)
    assert r["ttfs_s"] == 0.2


def test_absorb_records_a_stream_error():
    r = record()
    probe.absorb(r, sse({"error": {"message": "LoRA not found", "code": 404}}), 0.1)
    assert r["error"].startswith("stream error:") and "LoRA not found" in r["error"]


def measured(ttft, ttfs=None, error=None):
    return {"ttft_s": ttft, "ttfs_s": ttfs, "error": error}


def test_summary_percentiles_exclude_failures():
    records = [measured(float(i), float(i) + 1) for i in range(1, 21)]
    records.append(measured(None, None, error="HTTP 500: boom"))
    s = probe.summarise(records)
    assert (s["n"], s["failed"], s["ttft_n"], s["ttfs_n"]) == (21, 1, 20, 20)
    assert s["ttft_p50_s"] == pytest.approx(10.5)
    assert s["ttft_p95_s"] == pytest.approx(19.05)  # numpy.percentile(1..20, 95), linear
    assert s["ttfs_p50_s"] == pytest.approx(11.5)


def test_summary_edge_cases():
    s = probe.summarise([measured(0.4), measured(None, error="ReadTimeout: x")])
    assert (s["ttft_p50_s"], s["ttft_p95_s"], s["ttfs_n"], s["ttfs_p50_s"]) == (0.4, 0.4, 0, None)
    assert probe.summarise([])["ttft_p50_s"] is None


def test_prompt_logprobs_reads_the_actual_token_at_each_completion_position():
    ids = [11, 22, 33, 44]
    body = {"choices": [{"prompt_logprobs": [
        None,
        {"22": {"logprob": -1.0, "rank": 1}},
        {"33": {"logprob": -2.5, "rank": 3}, "7": {"logprob": -0.1, "rank": 1}},
        {"44": {"logprob": -0.25, "rank": 1}}]}]}
    assert probe.prompt_logprobs(body, ids, start=2) == [-2.5, -0.25]
