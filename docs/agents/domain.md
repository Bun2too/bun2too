# Domain docs

Layout: **multi-context**. Each product has its own domain language and decisions; the root holds only organisation-wide decisions.

| Context           | Glossary                                 | ADRs                                   |
| ----------------- | ---------------------------------------- | -------------------------------------- |
| Organisation      | (none yet)                               | `docs/adr/`                            |
| Support agent     | `bun2too-support-agent/GLOSSARY.md`      | `bun2too-support-agent/docs/adr/`      |
| Crew team         | `bun2too-crew-team/docs/` (see its AGENTS.md)    | (none yet)                             |
| Website           | `bun2too-website/docs/` (see its AGENTS.md) | (none yet)                          |

Rules for agents:

1. Read the glossary of the product you touch once per session before writing code or specs.
2. Before changing an area, list the product's `docs/adr/` and the root `docs/adr/`, and read any ADR whose title touches the area.
3. If your change contradicts an ADR, stop. Either write a superseding ADR in the same PR or raise it with a person.
4. When `/grill-with-docs` sharpens or adds a term, edit that product's glossary in place.
5. Use `docs/adr/0000-template.md` for new ADRs.
