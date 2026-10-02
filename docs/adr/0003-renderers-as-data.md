# ADR-0003: Renderers as data, with sandboxing and no public network renderer

- Status: Accepted
- Date: 2026-10-02

## Context

Every target format already has a command-line renderer: `mmdc` (Mermaid), `plantuml`,
`d2`, `dot` (Graphviz), `structurizr-cli`. A renderer is therefore an argv plus input and
output conventions. Structurizr is the exception: one DSL file exports to several views,
each of which needs a second renderer (PlantUML).

Diagram sources are produced by agents and must be treated as untrusted input. PlantUML
supports `!include` of files and URLs; Mermaid runs in headless Chromium. Some diagrams
come from work projects and must not leave the machine.

## Decision

- Declare renderers in `renderers.toml` (bundled), overridable key by key from the plugin
  config dir. Fields: `detect`, `argv` with placeholders, `in_ext`, `out`, `stdio`,
  `timeout`, `env`, and for multi-view tools `fanout` (glob) and `then` (next renderer,
  depth 1).
- No renderer classes and no Python plugin mechanism.
- Run argv without a shell. Cache artifacts by `sha256(format, renderer entry, source)`.
- Security defaults: PlantUML with `PLANTUML_SECURITY_PROFILE=SANDBOX`; Mermaid with the
  Chromium sandbox on and network blocked; limits of 1 MiB source, 20 MiB artifact, 30 s.
- No network renderer by default. Kroki may be added by the user as a self-hosted entry;
  the public kroki.io is never a bundled default.

Alternatives rejected:

- **A renderer class per format**: fails the deletion test — each class would only wrap an
  argv. Revisit only if a renderer needs logic that the fields cannot express.
- **Kroki as the single backend**: one dependency for every format, but it needs Docker or
  sends diagrams to a third party.

## Consequences

- Adding Graphviz or BPMN is a TOML edit plus a fixture.
- Users can repoint a renderer (for example a PlantUML jar via `java -jar`) without code changes.
- Chains deeper than one step or renderers needing pre-processing will force a schema
  extension; that is the signal to reconsider code-based renderers.
- Rendering quality and speed depend on external tools; `doctor` reports what is missing.
