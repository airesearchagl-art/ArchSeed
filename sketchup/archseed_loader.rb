# frozen_string_literal: true

require 'json'

module ArchSeed
  MM_TO_INCH = 1.0 / 25.4 unless const_defined?(:MM_TO_INCH, false)
  DEFAULT_WALL_THICKNESS_MM = 150.0 unless const_defined?(:DEFAULT_WALL_THICKNESS_MM, false)
  DEFAULT_SLAB_THICKNESS_MM = 180.0 unless const_defined?(:DEFAULT_SLAB_THICKNESS_MM, false)
  DEFAULT_PARAPET_HEIGHT_MM = 300.0 unless const_defined?(:DEFAULT_PARAPET_HEIGHT_MM, false)

  module_function

  def import_json(path = nil)
    selected_path = path || UI.openpanel('Open ArchSeed JSON', nil, 'JSON Files|*.json||')
    return unless selected_path

    data = JSON.parse(File.read(selected_path, encoding: 'UTF-8'))
    validate!(data)
    build_model(data)
    UI.messagebox("ArchSeed import complete: #{data.fetch('project').fetch('name')}")
  rescue JSON::ParserError, KeyError, TypeError, ArgumentError => e
    UI.messagebox("ArchSeed import failed:\n#{e.message}")
  end

  def validate!(data)
    object!(data, '$')
    expect_value!(data, 'schemaVersion', 'archseed.v0.1', '$')
    expect_value!(data, 'units', 'mm', '$')

    project = object!(data.fetch('project'), '$.project')
    string!(project.fetch('name'), '$.project.name')

    building = object!(data.fetch('building'), '$.building')
    footprint = object!(building.fetch('footprint'), '$.building.footprint')
    positive_number!(footprint.fetch('width'), '$.building.footprint.width')
    positive_number!(footprint.fetch('depth'), '$.building.footprint.depth')

    levels = building.fetch('levels')
    raise ArgumentError, '$.building.levels must be a non-empty array' unless levels.is_a?(Array) && !levels.empty?

    levels.each_with_index do |level, index|
      object!(level, "$.building.levels[#{index}]")
      string!(level.fetch('name'), "$.building.levels[#{index}].name")
      positive_number!(level.fetch('height'), "$.building.levels[#{index}].height")
    end
  end

  def build_model(data)
    model = Sketchup.active_model
    model.start_operation('Import ArchSeed JSON', true)

    building = data.fetch('building')
    width = mm(building.fetch('footprint').fetch('width'))
    depth = mm(building.fetch('footprint').fetch('depth'))
    wall = mm(building.fetch('wallThickness', DEFAULT_WALL_THICKNESS_MM))
    slab = mm(building.fetch('slabThickness', DEFAULT_SLAB_THICKNESS_MM))

    project_name = data.fetch('project').fetch('name')
    building_group = add_named_group(model.active_entities, "ArchSeed Building - #{project_name}")
    floor_group = add_named_group(building_group.entities, 'ArchSeed Floor')
    walls_group = add_named_group(building_group.entities, 'ArchSeed Walls')
    roof_group = add_named_group(building_group.entities, 'ArchSeed Roof')

    z = 0.0
    building.fetch('levels').each do |level|
      height = mm(level.fetch('height'))
      add_slab(floor_group.entities, width, depth, slab, z)
      add_walls(walls_group.entities, width, depth, wall, height, z + slab)
      z += height
    end

    add_roof(roof_group.entities, building, width, depth, wall, slab, z)
    model.commit_operation
  rescue StandardError
    model.abort_operation if model
    raise
  end

  def add_named_group(entities, name)
    group = entities.add_group
    group.name = name
    group
  end

  def add_slab(entities, width, depth, thickness, z)
    add_box(entities, [0, 0, z], width, depth, thickness)
  end

  def add_walls(entities, width, depth, wall, height, base_z)
    add_box(entities, [0, 0, base_z], width, wall, height)
    add_box(entities, [0, depth - wall, base_z], width, wall, height)
    add_box(entities, [0, wall, base_z], wall, depth - (wall * 2), height)
    add_box(entities, [width - wall, wall, base_z], wall, depth - (wall * 2), height)
  end

  def add_roof(entities, building, width, depth, wall, slab, z)
    add_box(entities, [0, 0, z], width, depth, slab)
    roof = building.fetch('roof', { 'type' => 'flat', 'parapetHeight' => DEFAULT_PARAPET_HEIGHT_MM })
    parapet_height = mm(roof.fetch('parapetHeight', DEFAULT_PARAPET_HEIGHT_MM))
    return unless parapet_height.positive?

    add_walls(entities, width, depth, wall, parapet_height, z + slab)
  end

  def add_box(entities, origin, width, depth, height)
    x, y, z = origin
    points = [
      [x, y, z],
      [x + width, y, z],
      [x + width, y + depth, z],
      [x, y + depth, z]
    ]
    face = entities.add_face(points)
    face.reverse! if face.normal.z < 0
    face.pushpull(height)
  end

  def mm(value)
    value.to_f * MM_TO_INCH
  end

  def object!(value, path)
    raise ArgumentError, "#{path} must be an object" unless value.is_a?(Hash)

    value
  end

  def string!(value, path)
    raise ArgumentError, "#{path} must be a non-empty string" unless value.is_a?(String) && !value.strip.empty?

    value
  end

  def positive_number!(value, path)
    unless value.is_a?(Numeric) && value.positive?
      raise ArgumentError, "#{path} must be a positive number"
    end

    value
  end

  def expect_value!(data, key, expected, path)
    actual = data.fetch(key)
    raise ArgumentError, "#{path}.#{key} must be #{expected.inspect}" unless actual == expected
  end
end

unless file_loaded?(__FILE__)
  UI.menu('Plugins').add_item('ArchSeed Import JSON') { ArchSeed.import_json }
  file_loaded(__FILE__)
end
