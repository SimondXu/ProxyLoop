import json

import httpx
import pytest

from scripts.mod import probe
from serving import config

MODEL = "Qwen3.5-9B"


def record(model: str = MODEL) -> dict:
    return probe.new_record(model, "measured", 0)


def sse(obj) -> str:
    return "data: " + json.dumps(obj)


def chunk(text: str, finish: str | None = None, model: str = MODEL) -> str:
    return sse({"id": "cmpl-pl-probe-1", "model": model,
                "choices": [{"index": 0, "text": text, "finish_reason": finish}]})


def test_absorb_times_first_token_and_first_sentence():
    r = record()
    probe.absorb(r, ": keep-alive", 0.01)
    probe.absorb(r, chunk(""), 0.05)
    assert r["ttft_s"] is None
    probe.absorb(r, chunk("Sure"), 0.10)
    probe.absorb(r, chunk(", the total is 3.5"), 0.20)
    assert (r["ttft_s"], r["ttfs_s"]) == (0.10, None)
    probe.absorb(r, chunk(" dollars. Anything"), 0.30)
    probe.absorb(r, chunk(" else?", finish="stop"), 0.40)
    probe.absorb(r, sse({"id": "cmpl-pl-probe-1", "model": MODEL, "choices": [],
                         "usage": {"prompt_tokens": 1500, "completion_tokens": 9}}), 0.41)
    probe.absorb(r, "data: [DONE]", 0.42)
    assert (r["ttft_s"], r["ttfs_s"], r["finished"]) == (0.10, 0.30, True)
    assert r["text"] == "Sure, the total is 3.5 dollars. Anything else?"
    assert (r["server_id"], r["echoed_models"]) == ("cmpl-pl-probe-1", [MODEL])
    assert (r["prompt_tokens"], r["completion_tokens"]) == (1500, 9)
    assert r["error"] is None


def test_decimal_split_across_chunks_is_not_a_sentence_end():
    r = record()
    probe.absorb(r, chunk("Invoice 1003."), 0.1)
    assert r["ttfs_s"] is None
    probe.absorb(r, chunk("5 is due"), 0.2)
    probe.absorb(r, chunk(" now."), 0.3)
    assert r["ttfs_s"] is None  # a terminator at the end of the text counts only once finished
    probe.absorb(r, chunk("", finish="stop"), 0.4)
    assert r["ttfs_s"] == 0.4


def test_done_marker_finishes_the_stream():
    r = record()
    probe.absorb(r, chunk("Done."), 0.2)
    probe.absorb(r, "data: [DONE]", 0.25)
    assert (r["ttfs_s"], r["finished"]) == (0.25, True)


def test_no_sentence_end_leaves_ttfs_empty():
    r = record()
    probe.absorb(r, chunk("no terminator here", finish="length"), 0.2)
    assert r["finished"] and r["ttfs_s"] is None


def test_echoed_model_mismatch_is_an_error():
    r = record("Qwen3.5-9B-zero")
    probe.absorb(r, chunk("Hi.", model=MODEL), 0.1)
    assert "echoed model" in r["error"] and r["echoed_models"] == [MODEL]


def test_absorb_records_a_stream_error():
    r = record()
    probe.absorb(r, sse({"error": {"message": "LoRA not found", "code": 404}}), 0.1)
    assert r["error"].startswith("stream error:") and "LoRA not found" in r["error"]


def measured(ttft, ttfs=None, error=None):
    return {"ttft_s": ttft, "ttfs_s": ttfs, "error": error}


def test_summary_percentiles_and_failures():
    records = [measured(float(i), float(i) + 1) for i in range(1, 21)]
    records.append(measured(None, None, error="HTTP 500: boom"))
    s = probe.summarise(records)
    assert (s["n"], s["failed"], s["ttft_n"], s["ttfs_n"]) == (21, 1, 20, 20)
    assert s["ttft_p50_s"] == pytest.approx(10.5)
    assert s["ttft_p95_s"] == pytest.approx(19.05)  # numpy.percentile(1..20, 95), linear
    assert s["ttfs_p50_s"] == pytest.approx(11.5)
    assert s["ttfs_complete"] is False


def test_a_request_without_a_sentence_end_fails_ttfs_but_is_counted():
    s = probe.summarise([measured(0.4, 0.9), measured(0.5, None)])
    assert (s["n"], s["failed"], s["ttft_n"], s["ttfs_n"], s["ttfs_complete"]) == (2, 0, 2, 1, False)
    assert probe.summarise([measured(0.4, 0.6)])["ttfs_complete"] is True
    assert probe.summarise([])["ttft_p50_s"] is None


def block(ttft: float, ttfs: float) -> dict:
    return {"summary": {"ttft_p50_s": ttft, "ttfs_p50_s": ttfs}}


def test_derived_rows():
    zero, base = config.ZERO_LORA_NAME, config.SERVED_NAME
    lat = {f"{base}@c1": block(0.30, 0.50), f"{zero}@c1": block(0.32, 0.55),
           f"{base}@c4": block(0.40, 0.70), f"{zero}@c4": block(0.40, None), f"{base}@warmup": block(9, 9)}
    d = probe.derived(lat, None)
    assert d["lora_overhead"]["c1.ttft_p50_s"] == pytest.approx(0.02)
    assert d["lora_overhead"]["c4.ttfs_p50_s"] is None and "minus_baseline" not in d
    baseline = {"latency": {k: block(0.25, 0.45) for k in lat}}
    minus = probe.derived(lat, baseline)["minus_baseline"]
    assert minus[f"{base}@c1.ttft_p50_s"] == pytest.approx(0.05)
    assert not any("warmup" in k for k in minus)


def test_latency_prompt_shares_a_prefix_and_differs_at_the_end():
    a, b = probe.latency_messages(0, 30), probe.latency_messages(1, 30)
    assert a[0] == b[0] and a[1]["content"] != b[1]["content"]
    prefix = a[1]["content"].split("Request ")[0]
    assert b[1]["content"].startswith(prefix)


def keyless_client(statuses: dict[str, int]) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(statuses[request.url.path], json={})

    return httpx.Client(base_url="http://vllm.test", transport=httpx.MockTransport(handler))


def raw_report(keyless: dict[str, int]) -> dict:
    ok = {"complete": True, "max_abs_diff": 0.0, "mean_abs_diff": 0.0}
    summary = {"failed": 0, "ttfs_complete": True, "ttft_p50_s": 0.3, "ttfs_p50_s": 0.5}
    lat = {f"{m}@{b}": {"summary": summary}
           for m in (config.SERVED_NAME, config.ZERO_LORA_NAME) for b in ("warmup", "c1", "c4")}
    return {"keyless_status": keyless, "attest": {"runtime": {"lora_rung": "all"}},
            "tokenize": {"all_equal": True}, "latency": lat,
            "liveness": {"zero": ok, "live": {**ok, "mean_abs_diff": 0.01}}}


LADDER = {"summary": {"rung_ok:all": True}}


@pytest.mark.parametrize(("statuses", "expected"), [
    ({"/v1/models": 401, "/pl/attest": 401}, True),
    ({"/v1/models": 200, "/pl/attest": 401}, False),
    ({"/v1/models": 401, "/pl/attest": 200}, False),
])
def test_keyless_401_is_composed_from_both_protected_paths(statuses, expected):
    with keyless_client(statuses) as client:
        report = raw_report(probe.keyless_status(client))
    probe.evaluate(report, LADDER, None)
    assert report["keyless_status"] == statuses
    assert report["checks"]["keyless_401"] is expected
    assert probe.passed(report["checks"]) is expected


def test_evaluation_error_is_recorded_and_the_raw_run_kept(tmp_path, monkeypatch):
    report = raw_report({"/v1/models": 401, "/pl/attest": 401})
    monkeypatch.setattr(probe, "base_url", lambda variant: "http://vllm.test")
    monkeypatch.setattr(probe, "measure", lambda url, key, args: report)
    monkeypatch.setenv("PROXYLOOP_VLLM_API_KEY", "k3y")
    (tmp_path / "ladder.json").write_text(json.dumps({"summary": {}}))  # no rung_ok -> still evaluates
    del report["attest"]  # evaluate() will fail on the missing attest block
    out = tmp_path / "not-yet" / "probe.json"  # a missing parent dir is created
    assert probe.main(["--out", str(out), "--ladder", str(tmp_path / "ladder.json")]) == 1
    written = json.loads(out.read_text())
    assert written["evaluation_error"].startswith("KeyError")
    assert written["checks"] == {"evaluated": False}
    assert written["latency"] == json.loads(json.dumps(report["latency"]))
