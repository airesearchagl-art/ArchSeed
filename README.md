# ArchSeed

ArchSeed is an experimental JSON-first pipeline for generating simple architectural seed models that can later be opened in SketchUp.

v0.1 intentionally does not process natural language. The supported flow is:

```text
architectural JSON
-> JSON validation
-> fixed SketchUp Ruby builder functions
-> simple massing/building model
```

## v0.3 Quickstart

ArchSeed v0.3 provides a fully local, deterministic workflow from preset-based
text input to SketchUp import. It does not use an LLM API or perform general
natural-language understanding.

Use `generated/` as the workspace for generated JSON drafts. Files matching
`generated/*.json` are ignored by Git and must not be committed. Move a
reviewed draft into `examples/` only when intentionally promoting it to a
maintained example.

1. Generate a JSON draft:

```powershell
python tools/generate_archseed_json.py "small office with openings" --output generated/small_office_with_openings.v0.1.json
```

2. Validate the generated JSON:

```powershell
python tools/validate_archseed.py generated/small_office_with_openings.v0.1.json
```

3. Print the SketchUp import command:

```powershell
python tools/print_sketchup_import_command.py generated/small_office_with_openings.v0.1.json
```

4. Load the importer in the SketchUp Ruby Console, then paste the command
   printed by step 3:

```ruby
load "C:/Users/shuns/.codex/project/ArchSeed/sketchup/archseed_loader.rb"
ArchSeed.import_json("C:/Users/shuns/.codex/project/ArchSeed/generated/small_office_with_openings.v0.1.json")
```

The import helper resolves the JSON path to an absolute path and prints it with
`/` separators for the Ruby Console.

The generator maps these fixed keywords to v0.1-compatible presets:

- `simple house`
- `compact house`
- `small office`
- `two story`
- `openings` as a window and door modifier

Unknown input falls back to the simple house preset and writes a warning to
stderr. Add `--validate` to generate and validate in one command:

```powershell
python tools/generate_archseed_json.py "small office with openings" --output generated/small_office_with_openings.v0.1.json --validate
```

Validation failures return a non-zero exit code. Without `--output`, generated
JSON is written to stdout and validation messages are written to stderr.

## v0.4 Draft Sessions

ArchSeed v0.4 preparation adds a local draft session format on top of the v0.3
generate, validate, and import-command workflow. It still uses fixed preset
keywords and does not use an LLM API or external API.

Create a generated ArchSeed JSON file and a session record together:

```powershell
python tools/create_draft_session.py "small office with openings" --output-session draft_sessions/small_office_with_openings.session.json --output-json generated/small_office_with_openings.v0.1.json
```

The session JSON records:

- `user_prompt`
- `generator_mode`
- `generated_archseed_json_path`
- `validation_status`
- `validation_message`
- `sketchup_import_command`
- `created_at`
- `notes`

Files matching `generated/*.json` and `draft_sessions/*.json` are local working
artifacts and are ignored by Git. Their `.gitkeep` files remain tracked.

When importing into SketchUp, do not paste a `file:///...` URL into the Ruby
Console. Paste the complete `ArchSeed.import_json("...")` line printed by
`tools/print_sketchup_import_command.py` or stored in the session JSON under
`sketchup_import_command`.

### Safe LLM Configuration Design

ArchSeed v0.4 uses LM Studio as the first local LLM server candidate. The
example configuration uses `provider: "lmstudio"`, `mode: "local"`, and the
default local endpoint `http://localhost:1234/v1`.

```powershell
python tools/validate_llm_config.py config/llm_config.example.json
```

Start Local Server in LM Studio, then check its OpenAI-compatible models
endpoint:

```powershell
python tools/check_lmstudio_server.py --config config/llm_config.example.json
```

The check performs only a local `GET /v1/models` request. It does not send a
prompt or generate content. The validator permits only `localhost` or
`127.0.0.1`, requires `allow_external_api` and `require_api_key` to remain
`false`, and limits output to ArchSeed v0.1 JSON without Markdown or executable
code.

Preview the prompt intended for a future local LM Studio request:

```powershell
python tools/preview_llm_prompt.py "small office with openings"
```

The preview validates `config/llm_config.example.json` and prints the planned
prompt to stdout. It does not contact LM Studio or perform LLM generation.

Generate an ArchSeed JSON candidate with the local LM Studio server:

```powershell
python tools/generate_with_lmstudio.py "small office with openings" --output-json generated/lmstudio_small_office_with_openings.v0.1.json --output-session draft_sessions/lmstudio_small_office_with_openings.session.json
```

The CLI reads the local `/models` list and prefers chat-oriented model names
such as `instruct`, `coder`, or `chat` while ignoring embedding models. If LM
Studio exposes multiple models, specify one explicitly when needed:

```powershell
python tools/generate_with_lmstudio.py "small office with openings" --model qwen3-coder-30b-a3b-instruct --output-json generated/lmstudio_small_office_with_openings.v0.1.json --output-session draft_sessions/lmstudio_small_office_with_openings.session.json
```

The generator sends the same output-constrained prompt to the local
`/chat/completions` endpoint, extracts the JSON object from the model response,
writes it to `generated/`, validates it with the ArchSeed validator, and records
the validation result plus the SketchUp import command in `draft_sessions/`.
Markdown fences are tolerated when extracting the JSON candidate, but the
generated result is treated only as data and is never evaluated as code.

If JSON extraction or validation fails, the CLI exits with a non-zero status and
writes an `INVALID` session record when possible. Model quality varies, so
review the generated JSON before importing it into SketchUp.

## v0.5 JSON Repair Loop

When local LM Studio generation returns a JSON object that fails ArchSeed
validation, the generator can make a limited repair attempt using the validator
error:

```powershell
python tools/generate_with_lmstudio.py "small office with openings" --output-json generated/lmstudio_small_office_with_openings.v0.1.json --output-session draft_sessions/lmstudio_small_office_with_openings.session.json --repair-attempts 1
```

The default is `--repair-attempts 0`, so repair is opt-in. Values from 0 through
3 are accepted. Repair runs only after validation fails, preserves the original
building intent and openings, and asks the local model to correct only the
reported validation error. The draft session records `repair_attempts`,
`repair_status`, `repair_messages`, and `final_validation_status`.

An existing invalid file can also be repaired directly:

```powershell
python tools/repair_archseed_json.py generated/invalid.v0.1.json "$.building.footprint.width must be > 0 and <= 200000" --output generated/repaired.v0.1.json
```

### Repair Smoke Test

Create an intentionally invalid copy of a valid sample, confirm that validation
fails, ask the local LM Studio model to repair it, and validate the result:

```powershell
python tools/create_invalid_archseed_json.py examples/small_office.v0.1.json --output generated/invalid_small_office.v0.1.json
python tools/validate_archseed.py generated/invalid_small_office.v0.1.json
python tools/repair_archseed_json.py generated/invalid_small_office.v0.1.json --validation-error "Generated test invalid JSON should be repaired to ArchSeed v0.1 schema" --output generated/repaired_small_office.v0.1.json
python tools/validate_archseed.py generated/repaired_small_office.v0.1.json
python tools/print_sketchup_import_command.py generated/repaired_small_office.v0.1.json
```

The first validation command is expected to exit with a non-zero status. The
helper defaults to an invalid footprint dimension; `--corruption` also accepts
`missing-required` and `invalid-opening-wall`. Repair quality depends on the
loaded local model and prompt response, so a failed repair requires manual JSON
review. Both smoke-test files remain under `generated/` and outside Git
management.

After the repaired JSON is `VALID`, paste the complete
`ArchSeed.import_json("...")` line printed by
`tools/print_sketchup_import_command.py` into the SketchUp Ruby Console. Do not
paste a `file:///...` URL. Repair restores compatibility with the ArchSeed JSON
validation rules; it does not guarantee architectural quality. Inspect the
generated dimensions, openings, geometry, Tags, Outliner hierarchy, and
materials in SketchUp before accepting the result.

Every repaired candidate is saved as data and validated before success is
reported. The repair loop is not guaranteed to succeed; inspect the validator
message and repair the JSON manually when all attempts fail. It uses only the
configured LM Studio server on `localhost` or `127.0.0.1`, with no API key,
provider SDK, metered cloud API, or executable-code evaluation.

The draft session workflow remains fully local and output-constrained. ArchSeed
does not use metered cloud APIs, provider SDKs, API keys, or `.env` files in this
workflow. Files matching `generated/*.json` and `draft_sessions/*.json` remain
outside Git management.

## v0.6 Multiple Candidates

ArchSeed v0.6 can ask the configured LM Studio local server for multiple JSON
candidates, validate each candidate, optionally apply the existing repair loop,
and select one best candidate:

```powershell
python tools/generate_candidates_with_lmstudio.py "small office with openings" --count 3 --repair-attempts 1
```

Save the concise comparison as JSON when a review artifact is useful:

```powershell
python tools/generate_candidates_with_lmstudio.py "small office with openings" --count 3 --repair-attempts 1 --summary-json draft_sessions/candidates.summary.json
```

`--count` accepts 1 through 5 and defaults to 3. Each run writes candidates to
`generated/candidates/<run_id>/candidate_XX.v0.1.json`, copies the selected JSON
to `generated/candidates/<run_id>/best_candidate.v0.1.json`, and records the
comparison in `draft_sessions/<run_id>.candidates.session.json`.

Selection is deterministic: a `VALID` candidate is required, a candidate that
is valid without repair ranks above a repaired `VALID` candidate, and ties go
to the earlier candidate. The session records each candidate's validation and
repair status, `selected_candidate`, `selection_reason`, and the SketchUp import
command for the copied best candidate.

After generation, stdout lists each candidate's index, validation status,
repair status, final validation status, selection flag, and JSON path. The
`BEST CANDIDATE` section shows `selected_candidate`, explains the ranking in
`selection_reason`, and prints the complete `ArchSeed.import_json("...")` line
to paste into the SketchUp Ruby Console. The optional summary JSON contains the
same concise comparison without duplicating detailed validation and repair
messages from the full candidate session.

Files under `generated/candidates/`, including the best candidate, and files
matching `draft_sessions/*.json`, including summary JSON files, are local
artifacts outside Git management.
The workflow uses only LM Studio on `localhost` or `127.0.0.1`; it uses no API
key, external cloud API, or metered API. Selection confirms schema validity,
not architectural quality. Review the best candidate and its imported SketchUp
model visually before accepting it.

## v0.1 Scope

- Define a minimal `archseed.v0.1` JSON format.
- Validate JSON locally before importing it into SketchUp.
- Build a simple SketchUp model from fixed Ruby functions.
- Avoid dynamic code execution in SketchUp Ruby.

## v0.2 Editable Geometry

ArchSeed v0.1.0 generated the complete building geometry inside one group.
ArchSeed v0.2 keeps an overall building group, organizes floor and wall groups
under stable level groups, and keeps the roof as a separate group. This makes
each level and geometry category easier to find and edit in SketchUp without
changing the v0.1 schema version or import flow.

### Outliner Hierarchy

For `examples/simple_house.v0.1.json`, the generated groups are:

```text
ArchSeed Building - Simple House v0.1
|-- ArchSeed Level 1
|   |-- ArchSeed Floor - Level 1
|   |-- ArchSeed Walls - Level 1
|   `-- ArchSeed Openings - Level 1 (when defined)
|-- ArchSeed Level 2
|   |-- ArchSeed Floor - Level 2
|   `-- ArchSeed Walls - Level 2
`-- ArchSeed Roof
```

Level and element group names are derived from each validated JSON level name.

### SketchUp Tags

ArchSeed creates or reuses the following Tags and assigns them to generated
element Group instances:

- `ArchSeed Floor`
- `ArchSeed Walls`
- `ArchSeed Roof`
- `ArchSeed Openings`

Building and level wrapper Groups are explicitly kept `Untagged`. ArchSeed does
not assign category Tags to raw edges or faces; Tags are assigned only to Group
instances. This follows SketchUp modeling practice and allows category
visibility to be controlled from the Tags panel without changing the Outliner
hierarchy.

### SketchUp Materials

ArchSeed creates or reuses stable materials and applies them to generated
element Group instances:

- `ArchSeed Floor Material` - muted gray-green
- `ArchSeed Wall Material` - warm off-white
- `ArchSeed Roof Material` - blue-gray
- `ArchSeed Window Material` - semi-transparent blue
- `ArchSeed Door Material` - warm brown

The `ArchSeed Openings` wrapper keeps its category Tag without a single
material so its window and door child Groups remain visually distinct.
Materials are assigned independently from Tags and do not change the Outliner
hierarchy.

### Simple Opening Indicators

An optional `building.openings` array can place simple window and door
indicators on the north, south, east, or west wall of a level. Each opening
defines:

- `type`: `window` or `door`
- `level`: an exact level name or a zero-based level index
- `wall`: `north`, `south`, `east`, or `west`
- `offset_mm`, `width_mm`, and `height_mm`
- optional `sill_height_mm` (defaults to 900 mm for windows and 0 mm for doors)

These indicators are colored rectangular faces grouped under
`ArchSeed Openings - <level name>` and assigned the `ArchSeed Openings` Tag.
They show intended opening positions only. ArchSeed v0.2 does not cut or
boolean-subtract openings from wall geometry.

### Geometry Dimension Rules

- JSON dimensions are millimeters and are converted to SketchUp inches.
- A level `height` is the floor-to-floor distance from its slab bottom to the
  next level or roof slab bottom.
- The floor slab starts at the level base and uses `slabThickness` (default:
  180 mm).
- Walls start at the floor slab top and stop at the level top. Their clear
  generated height is therefore `level height - slab thickness`.
- Wall depth uses `wallThickness` (default: 150 mm).
- The flat roof slab starts at the final level top and uses the slab thickness.
- The parapet starts at the roof slab top and uses `parapetHeight` (default:
  300 mm).
- Floor, walls, and roof remain separate named groups inside the building group.

## Sample JSON Files

- `examples/simple_house.v0.1.json` - baseline two-level house sample
- `examples/small_office.v0.1.json` - single-level small office massing sample
- `examples/two_story_box.v0.1.json` - two-story box for level and height checks
- `examples/compact_house.v0.1.json` - single-level compact residential sample
- `examples/house_with_openings.v0.1.json` - window and door indicator sample

Import a specific sample from the SketchUp Ruby Console:

```ruby
ArchSeed.import_json("C:/Users/shuns/.codex/project/ArchSeed/examples/small_office.v0.1.json")
```

Import the opening indicator sample:

```ruby
ArchSeed.import_json("C:/Users/shuns/.codex/project/ArchSeed/examples/house_with_openings.v0.1.json")
```

## Repository Layout

```text
schemas/                     JSON Schema reference
examples/                    Minimal sample building JSON
tools/validate_archseed.py   Local JSON validator
tools/generate_with_lmstudio.py
                             Local LM Studio JSON generation helper
sketchup/archseed_loader.rb  SketchUp Ruby loader
tests/                       Python tests for validation and safety checks
```

## Quick Start

ArchSeed v0.1 includes a JSON Schema reference and a small Python validator.
The current Python validator implements the v0.1 validation rules directly.
A future version may switch to validating directly against the JSON Schema file.

Validate the sample JSON:

```powershell
python tools/validate_archseed.py examples/simple_house.v0.1.json
```

Run tests:

```powershell
python -m pytest
```

## SketchUp Usage

1. Open SketchUp.
2. Open the Ruby Console.
3. Load `sketchup/archseed_loader.rb`.
4. Run:

```ruby
ArchSeed.import_json
```

5. Select `examples/simple_house.v0.1.json`.

SketchUp stores model lengths internally in inches. ArchSeed v0.1 JSON uses millimeters and converts to inches at import time.

## Safety Policy

The SketchUp Ruby loader must not use:

- `eval`
- `instance_eval`
- `module_eval`
- `class_eval`
- `system`
- `exec`
- `spawn`
- backtick command execution
- arbitrary shell execution
- AI-generated Ruby code execution

The importer parses JSON data only and maps it to fixed geometry functions.
