# Coding standards

The Standards reviewer checks diffs against this file. Anything tooling already enforces (Biome, Ruff, mypy, tsc) is not repeated here. Where this file and the Fowler smell baseline in `/code-review` disagree, this file wins.

## Both languages

- **Parse, don't validate.** Turn untrusted input into domain types at the boundary (`IntakeRequest.parse`, `IntakeRequest.model_validate`). Functions below the boundary accept domain types, never `unknown`, `any`, `dict[str, Any]`.
- **Make illegal states unrepresentable.** Use discriminated unions (`kind`) and enums for status, intent and severity. No boolean pairs that can contradict each other.
- **Errors are values at seams.** Ports return typed results or raise one documented error type. No bare `except:` / `catch {}`. Never swallow an error to make a test pass.
- **Idempotency is part of the signature.** Any function that writes outside the process takes or derives a key, and calling it twice converges.
- **Names come from GLOSSARY.md.** A new concept gets a glossary entry in the same PR.
- **No dead code, no commented-out code, no TODO without an issue link.**

## TypeScript

- `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes` are on. Do not relax them per file.
- No `as` casts except `as const`. No `@ts-ignore`; `@ts-expect-error` only with a linked issue.
- Export types from `packages/contracts`; never redeclare a wire shape in an app.
- Hono handlers stay thin: parse, call a function, map the result to a response.
- Tests use Vitest and hit the app through `app.request()`; no mocking of internal modules.

## Python

- Python 3.12+, full type hints, `mypy --strict` clean.
- Pydantic v2 models for anything crossing a boundary; frozen dataclasses for internal values.
- Ports are `typing.Protocol`s in the module that consumes them. Adapters live in `connectors/`.
- Async all the way down for I/O. No `asyncio.run` inside library code.
- LangGraph nodes are pure functions of `(state, deps)` that return a partial state update. Side effects go through ports in `deps`.
- Tests use pytest with the offline wiring (`build_deps(..., {"RELAY_OFFLINE": "1"})`) and the fakes in `connectors/fakes.py`. Never patch internals with `monkeypatch` to reach a branch; add a seam instead.

## Prompts

- Prompts live in `relay_agents/prompts/<name>.md`. Each specialist records its prompt version on the `specialist finished` case event.
- Customer text enters prompts only through `as_untrusted()`.
- A prompt change ships with an eval run in the PR body (`pnpm eval`), before and after.
