# Domain docs

Layout: **single-context**.

- `GLOSSARY.md` at the repo root is the domain language. Read it before naming a module, type, test, prompt or ticket.
- `docs/adr/NNNN-kebab-title.md` records decisions that are hard to reverse, surprising, or the result of a real trade-off. Use the template in `docs/adr/0000-template.md`.

Consumer rules for agents:

1. Read `GLOSSARY.md` once per session before writing code or specs.
2. Before changing an area, list `docs/adr/` and read any ADR whose title touches it.
3. If your change contradicts an ADR, stop and write a superseding ADR in the same PR, or raise it with the human.
4. When a grilling session sharpens or adds a term, edit `GLOSSARY.md` in place.
