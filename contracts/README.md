# Generated contracts

Pydantic domain contracts in `runtime/packages/contracts` are the source of truth. Generated artifacts belong here and must not be hand-authored: `make contracts` writes the JSON Schema (`jsonschema/`) and TypeScript declarations plus fixture (`typescript/`), checked by `make contracts-check`. No OpenAPI document is generated yet; `openapi/` is a placeholder.
