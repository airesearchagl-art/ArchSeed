# ArchSeed

ArchSeed is an experimental JSON-first pipeline for generating simple architectural seed models that can later be opened in SketchUp.

v0.1 intentionally does not process natural language. The supported flow is:

```text
architectural JSON
-> JSON validation
-> fixed SketchUp Ruby builder functions
-> simple massing/building model
```

## v0.1 Scope

- Define a minimal `archseed.v0.1` JSON format.
- Validate JSON locally before importing it into SketchUp.
- Build a simple SketchUp model from fixed Ruby functions.
- Avoid dynamic code execution in SketchUp Ruby.

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

The v0.1 importer parses JSON data only and maps it to fixed geometry functions.
