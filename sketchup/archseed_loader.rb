# frozen_string_literal: true

require 'json'

module ArchSeed
  MM_TO_INCH = 1.0 / 25.4 unless const_defined?(:MM_TO_INCH, false)
  DEFAULT_WALL_THICKNESS_MM = 150.0 unless const_defined?(:DEFAULT_WALL_THICKNESS_MM, false)
  DEFAULT_SLAB_THICKNESS_MM = 180.0 unless const_defined?(:DEFAULT_SLAB_THICKNESS_MM, false)
  DEFAULT_PARAPET_HEIGHT_MM = 300.0 unless const_defined?(:DEFAULT_PARAPET_HEIGHT_MM, false)
  DEFAULT_WINDOW_SILL_HEIGHT_MM = 900.0 unless const_defined?(:DEFAULT_WINDOW_SILL_HEIGHT_MM, false)
  OPENING_INDICATOR_OFFSET_MM = 2.0 unless const_defined?(:OPENING_INDICATOR_OFFSET_MM, false)
  FLOOR_TAG_NAME = 'ArchSeed Floor' unless const_defined?(:FLOOR_TAG_NAME, false)
  WALLS_TAG_NAME = 'ArchSeed Walls' unless const_defined?(:WALLS_TAG_NAME, false)
  ROOF_TAG_NAME = 'ArchSeed Roof' unless const_defined?(:ROOF_TAG_NAME, false)
  OPENINGS_TAG_NAME = 'ArchSeed Openings' unless const_defined?(:OPENINGS_TAG_NAME, false)
  FLOOR_MATERIAL_NAME = 'ArchSeed Floor Material' unless const_defined?(:FLOOR_MATERIAL_NAME, false)
  WALL_MATERIAL_NAME = 'ArchSeed Wall Material' unless const_defined?(:WALL_MATERIAL_NAME, false)
  ROOF_MATERIAL_NAME = 'ArchSeed Roof Material' unless const_defined?(:ROOF_MATERIAL_NAME, false)
  WINDOW_MATERIAL_NAME = 'ArchSeed Window Material' unless const_defined?(:WINDOW_MATERIAL_NAME, false)
  DOOR_MATERIAL_NAME = 'ArchSeed Door Material' unless const_defined?(:DOOR_MATERIAL_NAME, false)
  MATERIAL_STYLES = {
    FLOOR_MATERIAL_NAME => [[175, 180, 170], 1.0],
    WALL_MATERIAL_NAME => [[225, 218, 200], 1.0],
    ROOF_MATERIAL_NAME => [[155, 165, 180], 1.0],
    WINDOW_MATERIAL_NAME => [[70, 160, 220], 0.55],
    DOOR_MATERIAL_NAME => [[170, 110, 70], 0.8]
  }.freeze unless const_defined?(:MATERIAL_STYLES, false)

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

    validate_openings!(building, levels, footprint)
  end

  def build_model(data)
    model = Sketchup.active_model
    model.start_operation('Import ArchSeed JSON', true)

    building = data.fetch('building')
    width = mm(building.fetch('footprint').fetch('width'))
    depth = mm(building.fetch('footprint').fetch('depth'))
    wall = mm(building.fetch('wallThickness', DEFAULT_WALL_THICKNESS_MM))
    slab = mm(building.fetch('slabThickness', DEFAULT_SLAB_THICKNESS_MM))
    untagged = model.layers[0]
    floor_tag = find_or_create_tag(model, FLOOR_TAG_NAME)
    walls_tag = find_or_create_tag(model, WALLS_TAG_NAME)
    roof_tag = find_or_create_tag(model, ROOF_TAG_NAME)
    openings = building.fetch('openings', [])
    openings_tag = openings.empty? ? nil : find_or_create_tag(model, OPENINGS_TAG_NAME)
    floor_material = find_or_create_material(model, FLOOR_MATERIAL_NAME)
    wall_material = find_or_create_material(model, WALL_MATERIAL_NAME)
    roof_material = find_or_create_material(model, ROOF_MATERIAL_NAME)

    project_name = data.fetch('project').fetch('name')
    building_group = add_named_group(model.active_entities, "ArchSeed Building - #{project_name}", untagged)

    level_bottom_z = 0.0
    levels = building.fetch('levels')
    levels.each_with_index do |level, level_index|
      level_name = level.fetch('name')
      story_height = mm(level.fetch('height'))
      floor_bottom_z = level_bottom_z
      floor_top_z = floor_bottom_z + slab
      wall_bottom_z = floor_top_z
      wall_top_z = level_bottom_z + story_height
      wall_height = wall_top_z - wall_bottom_z
      unless wall_height.positive?
        raise ArgumentError, "#{level_name} height must exceed slab thickness"
      end

      level_group = add_named_group(building_group.entities, "ArchSeed #{level_name}", untagged)
      floor_group = add_named_group(
        level_group.entities,
        "ArchSeed Floor - #{level_name}",
        floor_tag,
        floor_material
      )
      walls_group = add_named_group(
        level_group.entities,
        "ArchSeed Walls - #{level_name}",
        walls_tag,
        wall_material
      )
      add_slab(floor_group.entities, width, depth, slab, floor_bottom_z)
      add_walls(walls_group.entities, width, depth, wall, wall_height, wall_bottom_z)
      level_openings = openings.select do |opening|
        resolve_level_index(levels, opening.fetch('level'), '$.building.openings') == level_index
      end
      unless level_openings.empty?
        openings_group = add_named_group(
          level_group.entities,
          "ArchSeed Openings - #{level_name}",
          openings_tag
        )
        level_openings.each do |opening|
          add_opening_indicator(
            model,
            openings_group.entities,
            opening,
            level_name,
            width,
            depth,
            wall_bottom_z,
            openings_tag
          )
        end
      end
      level_bottom_z = wall_top_z
    end

    roof_bottom_z = level_bottom_z
    roof_group = add_named_group(
      building_group.entities,
      'ArchSeed Roof',
      roof_tag,
      roof_material
    )
    add_roof(roof_group.entities, building, width, depth, wall, slab, roof_bottom_z)
    model.commit_operation
  rescue StandardError
    model.abort_operation if model
    raise
  end

  def find_or_create_tag(model, name)
    tags = model.layers
    tags[name] || tags.add(name)
  end

  def add_named_group(entities, name, tag = nil, material = nil)
    group = entities.add_group
    group.name = name
    group.layer = tag if tag
    group.material = material if material
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

  def add_roof(entities, building, width, depth, wall, slab, roof_bottom_z)
    roof_top_z = roof_bottom_z + slab
    add_box(entities, [0, 0, roof_bottom_z], width, depth, slab)
    roof = building.fetch('roof', { 'type' => 'flat', 'parapetHeight' => DEFAULT_PARAPET_HEIGHT_MM })
    parapet_height = mm(roof.fetch('parapetHeight', DEFAULT_PARAPET_HEIGHT_MM))
    return unless parapet_height.positive?

    add_walls(entities, width, depth, wall, parapet_height, roof_top_z)
  end

  def add_opening_indicator(model, entities, opening, level_name, width, depth, wall_bottom_z, tag)
    opening_type = opening.fetch('type')
    offset = mm(opening.fetch('offset_mm'))
    opening_width = mm(opening.fetch('width_mm'))
    opening_height = mm(opening.fetch('height_mm'))
    default_sill = opening_type == 'window' ? DEFAULT_WINDOW_SILL_HEIGHT_MM : 0.0
    sill_height = mm(opening.fetch('sill_height_mm', default_sill))
    base_z = wall_bottom_z + sill_height
    indicator_offset = mm(OPENING_INDICATOR_OFFSET_MM)
    points = opening_points(
      opening.fetch('wall'),
      offset,
      opening_width,
      opening_height,
      base_z,
      width,
      depth,
      indicator_offset
    )

    label = opening_type == 'window' ? 'Window' : 'Door'
    material_name = opening_type == 'window' ? WINDOW_MATERIAL_NAME : DOOR_MATERIAL_NAME
    material = find_or_create_material(model, material_name)
    opening_group = add_named_group(
      entities,
      "ArchSeed #{label} - #{level_name}",
      tag,
      material
    )
    face = opening_group.entities.add_face(points)
    raise ArgumentError, "Could not create #{opening_type} indicator" unless face

    face.material = material
    face.back_material = material
  end

  def opening_points(wall_name, offset, width, height, base_z, building_width, building_depth, gap)
    case wall_name
    when 'south'
      y = -gap
      [[offset, y, base_z], [offset + width, y, base_z], [offset + width, y, base_z + height], [offset, y, base_z + height]]
    when 'north'
      y = building_depth + gap
      [[offset, y, base_z], [offset, y, base_z + height], [offset + width, y, base_z + height], [offset + width, y, base_z]]
    when 'west'
      x = -gap
      [[x, offset, base_z], [x, offset, base_z + height], [x, offset + width, base_z + height], [x, offset + width, base_z]]
    when 'east'
      x = building_width + gap
      [[x, offset, base_z], [x, offset + width, base_z], [x, offset + width, base_z + height], [x, offset, base_z + height]]
    else
      raise ArgumentError, "Unsupported wall: #{wall_name}"
    end
  end

  def find_or_create_material(model, name)
    color, alpha = MATERIAL_STYLES.fetch(name)
    material = model.materials[name] || model.materials.add(name)
    material.color = Sketchup::Color.new(*color)
    material.alpha = alpha
    material
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

  def non_negative_number!(value, path)
    unless value.is_a?(Numeric) && value >= 0
      raise ArgumentError, "#{path} must be a non-negative number"
    end

    value
  end

  def validate_openings!(building, levels, footprint)
    openings = building.fetch('openings', [])
    unless openings.is_a?(Array) && openings.length <= 200
      raise ArgumentError, '$.building.openings must be an array with at most 200 items'
    end

    slab_thickness = positive_number!(
      building.fetch('slabThickness', DEFAULT_SLAB_THICKNESS_MM),
      '$.building.slabThickness'
    )
    openings.each_with_index do |opening, index|
      path = "$.building.openings[#{index}]"
      object!(opening, path)
      opening_type = opening.fetch('type')
      unless %w[window door].include?(opening_type)
        raise ArgumentError, "#{path}.type must be window or door"
      end

      level_index = resolve_level_index(levels, opening.fetch('level'), path)
      wall_name = opening.fetch('wall')
      unless %w[north south east west].include?(wall_name)
        raise ArgumentError, "#{path}.wall must be north, south, east, or west"
      end

      offset = non_negative_number!(opening.fetch('offset_mm'), "#{path}.offset_mm")
      width = positive_number!(opening.fetch('width_mm'), "#{path}.width_mm")
      height = positive_number!(opening.fetch('height_mm'), "#{path}.height_mm")
      default_sill = opening_type == 'window' ? DEFAULT_WINDOW_SILL_HEIGHT_MM : 0.0
      sill = non_negative_number!(
        opening.fetch('sill_height_mm', default_sill),
        "#{path}.sill_height_mm"
      )

      wall_span = %w[north south].include?(wall_name) ? footprint.fetch('width') : footprint.fetch('depth')
      raise ArgumentError, "#{path} extends beyond its wall" if offset + width > wall_span

      wall_height = levels[level_index].fetch('height') - slab_thickness
      raise ArgumentError, "#{path} extends above the generated wall" if sill + height > wall_height
    end
  end

  def resolve_level_index(levels, reference, path)
    if reference.is_a?(Integer)
      return reference if reference >= 0 && reference < levels.length
    elsif reference.is_a?(String)
      index = levels.index { |level| level.fetch('name') == reference }
      return index if index
    end

    raise ArgumentError, "#{path}.level must match a level name or zero-based index"
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
