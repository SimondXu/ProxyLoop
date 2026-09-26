"""Adapter liveness (ARCHITECTURE §13): prompt_logprobs of fixed completions, base vs a
LoRA slot, in the same served process. Used by the serving probe and by pull-through.

Zero-initialised adapter: max |Δ| <= ZERO_MAX_DIFF. Non-zero adapter: mean |Δ| >
LIVE_MIN_MEAN_DIFF. Every response must echo the requested model; a mismatch or an HTTP
error fails the comparison.
"""

from typing import TYPE_CHECKING, Any

from serving import config

if TYPE_CHECKING:
    import httpx


def prompt_logprobs(body: dict[str, Any], ids: list[int], start: int) -> list[float]:
    """Logprob of the actual token at each completion position of a /v1/completions
    body."""
    rows: list[Any] = body["choices"][0]["prompt_logprobs"]
    return [rows[i][str(ids[i])]["logprob"] for i in range(start, len(ids))]


def read_response(
    model: str, status: int, body: dict[str, Any] | None, ids: list[int], start: int
) -> dict[str, Any]:
    """One side of a pair: {server_id, echoed_model, logprobs} or {error}."""
    if status != 200 or body is None:
        return {"status": status, "error": f"HTTP {status}"}
    out: dict[str, Any] = {
        "status": status,
        "server_id": body.get("id"),
        "echoed_model": body.get("model"),
    }
    if out["echoed_model"] != model:
        return {
            **out,
            "error": f"echoed model {out['echoed_model']!r} != requested {model!r}",
        }
    return {**out, "logprobs": prompt_logprobs(body, ids, start)}


def compare(
    client: "httpx.Client", pairs: list[tuple[list[int], int]], lora: str
) -> dict[str, Any]:
    """`client` is an httpx.Client bound to the server, with the bearer header set."""
    rows: list[dict[str, Any]] = []
    diffs: list[float] = []
    for ids, start in pairs:
        row: dict[str, Any] = {}
        for label, model in (("base", config.SERVED_NAME), ("lora", lora)):
            resp = client.post(
                "/v1/completions",
                json={
                    "model": model,
                    "prompt": ids,
                    "max_tokens": 1,
                    "temperature": 0,
                    "prompt_logprobs": 0,
                },
            )
            row[label] = read_response(
                model,
                resp.status_code,
                resp.json() if resp.status_code == 200 else None,
                ids,
                start,
            )
        if not any("error" in side for side in row.values()):
            row["abs_diff"] = [
                abs(a - b)
                for a, b in zip(
                    row["base"]["logprobs"], row["lora"]["logprobs"], strict=True
                )
            ]
            diffs += row["abs_diff"]
        rows.append(row)
    ok = bool(diffs) and all("abs_diff" in r for r in rows)
    return {
        "lora": lora,
        "pairs": rows,
        "complete": ok,
        "max_abs_diff": max(diffs) if ok else None,
        "mean_abs_diff": sum(diffs) / len(diffs) if ok else None,
    }


def zero_ok(result: dict[str, Any]) -> bool:
    return result["complete"] and result["max_abs_diff"] <= config.ZERO_MAX_DIFF


def live_ok(result: dict[str, Any]) -> bool:
    return result["complete"] and result["mean_abs_diff"] > config.LIVE_MIN_MEAN_DIFF
