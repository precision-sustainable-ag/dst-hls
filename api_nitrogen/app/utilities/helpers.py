import numpy as np
from shapely.ops import transform
from pyproj import Transformer
from shapely.geometry import box, shape, mapping
from shapely.ops import orient

def create_biomass_geojson(biomass_data, bbox, grid_size_acres):
    features = []

    # Filter out zero values for min/max calculation
    flattened_biomass = biomass_data.flatten()
    non_zero_biomass = flattened_biomass[flattened_biomass > 0]

    if len(non_zero_biomass) == 0:
        return {
            "type": "FeatureCollection",
            "features": []
        }

    biomass_max = float(np.max(non_zero_biomass))
    biomass_min = float(np.min(non_zero_biomass))
    value_range = biomass_max - biomass_min

    # Grid dimensions
    h, w = biomass_data.shape  # Note: shape is (height, width)

    lon_min = min(bbox[0], bbox[2])
    lon_max = max(bbox[0], bbox[2])
    lat_min = min(bbox[1], bbox[3])
    lat_max = max(bbox[1], bbox[3])

    dLon = (lon_max - lon_min) / w
    dLat = (lat_max - lat_min) / h

    # Build polygon features
    for i in range(w):
        for j in range(h):
            biomass_val = float(biomass_data[j, i])

            # Skip invalid or zero values
            if biomass_val == 0 or biomass_val == -9999:
                continue

            # Calculate corner coordinates
            top_left_lon = lon_min + i * dLon
            top_left_lat = lat_max - j * dLat  # Start from top (max lat)

            # Create polygon coordinates (closed ring)
            # polygon_coords = [[
            #     [top_left_lon, top_left_lat],
            #     [top_left_lon + dLon, top_left_lat],
            #     [top_left_lon + dLon, top_left_lat - dLat],
            #     [top_left_lon, top_left_lat - dLat],
            #     [top_left_lon, top_left_lat]
            # ]]
            cell_geom = box(top_left_lon, top_left_lat - dLat, top_left_lon + dLon, top_left_lat)

            # Calculate normalized value for color mapping
            # normalized_val = (biomass_val - biomass_min) / value_range if value_range > 0 else 0

            # properties = {
            #         "value": biomass_val,
            #         "normalized_value": normalized_val,
            #         "row": j,
            #         "col": i
            # }

            # if mode == 'pm3d':
            #         species_data = {}
            #         for species_name, species_array in species_biomass_average.items():
            #             species_val = float(species_array[j][i])
            #             if species_val > 0:
            #                 species_data[species_name] = species_val

            #         properties["species"] = species_data

            # Create feature
            # feature = {
            #     "type": "Feature",
            #     "geometry": {"type": "Polygon", "coordinates": polygon_coords},
            #     "properties": properties
            # }

            # features.append(feature)
            features.append({'geom': cell_geom, 'biomass_average': biomass_val})

    # Generate new grid based on grid_size_acres

    target_area_m2 = grid_size_acres * 4046.86 # (1 acre = 4046.86 m2)
    side_length_m = np.sqrt(target_area_m2)

    project_to_m = Transformer.from_crs("EPSG:4326", "EPSG:6933", always_xy=True).transform
    project_to_deg = Transformer.from_crs("EPSG:6933", "EPSG:4326", always_xy=True).transform

    # Project the corner points of bbox from degrees to meters
    min_pt = transform(project_to_m, box(lon_min, lat_min, lon_min, lat_min).centroid)
    max_pt = transform(project_to_m, box(lon_max, lat_max, lon_max, lat_max).centroid)

    width_m = abs(max_pt.x - min_pt.x)
    height_m = abs(max_pt.y - min_pt.y)

    # Determine the number of columns and rows needed for the grid
    cols = int(np.ceil(width_m / side_length_m))
    rows = int(np.ceil(height_m / side_length_m))

    new_features = []

    for r in range(rows):
        for c in range(cols):
            # Calculate corner coordinates
            x_min = min_pt.x + (c * side_length_m)
            y_max = max_pt.y - (r * side_length_m)

            new_cell_m = box(x_min, y_max - side_length_m, x_min + side_length_m, y_max)
            new_cell_deg = transform(project_to_deg, new_cell_m)

            weighted_sum = 0
            total_intersect_area = 0

            # Calculate weighted average biomass for the new cell based on intersecting features
            for feature in features:
                feat_geom = feature['geom']
                cell_intersection = new_cell_deg.intersection(feat_geom)

                if not cell_intersection.is_empty:
                    cell_intersection_area = transform(project_to_m, cell_intersection).area

                    weighted_sum += feature['biomass_average'] * cell_intersection_area
                    total_intersect_area += cell_intersection_area

            if total_intersect_area > 0:
                final_biomass = weighted_sum / total_intersect_area

                new_features.append({
                    "type": "Feature",
                    "geometry": mapping(orient(new_cell_deg, sign=1.0)),
                    "properties": {
                        "biomass_average": final_biomass,
                        "row": r,
                        "col": c
                    }
                })

    return {
        "type": "FeatureCollection",
        "features": new_features,
        "properties": {
            "biomass_min": biomass_min,
            "biomass_max": biomass_max,
            "value_range": value_range
        }
    }

def get_center(feature):
    geom = shape(feature["geometry"])
    centroid = geom.centroid
    return (centroid.x, centroid.y)