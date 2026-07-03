# ArchSeed

ArchSeed is an experimental JSON-first pipeline for generating simple architectural seed models that can later be opened in SketchUp.

v0.1 intentionally does not process natural language. The supported flow is:

```text
architectural JSON
-> JSON validation
-> fixed SketchUp Ruby builder functions
-> simple massing/building model
```

## v0.3 JSON Draft CLI

ArchSeed v0.3 starts with a deterministic draft generator for short,
natural-language-like descriptions. It does not use an LLM API and does not
perform general natural-language understanding. It maps fixed keywords to
v0.1-compatible presets:

- `simple house`
- `compact house`
- `small office`
- `two story`
- `openings` as a window and door modifier

Unknown input falls back to the simple house preset and writes a warning to
stderr.

Generate a draft to stdout:

```powershell
python tools/generate_archseed_json.py "simple house"
```

Generate and save a draft:

```powershell
python tools/generate_archseed_json.py "simple house" --output generated/simple_house.v0.1.json
```

Generate, validate, and save a draft in one command:

```powershell
python tools/generate_archseed_json.py "small office with openings" --output generated/small_office_with_openings.v0.1.json --validate
```

`--validate` uses the existing ArchSeed validator. Validation failures return a
non-zero exit code. Without `--output`, JSON remains on stdout and the
validation result is written to stderr.

The generated file can also be validated separately:

```powershell
python tools/validate_archseed.py generated/small_office_with_openings.v0.1.json
```

Print the absolute import command with `/` path separators:

```powershell
python tools/print_sketchup_import_command.py generated/small_office_with_openings.v0.1.json
```

Copy the printed command into the SketchUp Ruby Console after loading the
importer:

```ruby
load "C:/Users/shuns/.codex/project/ArchSeed/sketchup/archseed_loader.rb"
ArchSeed.import_json("C:/Users/shuns/.codex/project/ArchSeed/generated/small_office_with_openings.v0.1.json")
```

This generate, validate, and import-command workflow is fully local and does
not use an LLM API.

The `generated/` directory is the recommended workspace for generated JSON
drafts. Its JSON files are ignored by Git and should not be committed. Move a
reviewed draft into `examples/` only when intentionally promoting it to a
maintained example.

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
