import numpy as np

def create_biomass_geojson(biomass_data, bbox, mode, species_biomass_average):
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
            polygon_coords = [[
                [top_left_lon, top_left_lat],
                [top_left_lon + dLon, top_left_lat],
                [top_left_lon + dLon, top_left_lat - dLat],
                [top_left_lon, top_left_lat - dLat],
                [top_left_lon, top_left_lat]
            ]]

            # Calculate normalized value for color mapping
            normalized_val = (biomass_val - biomass_min) / value_range if value_range > 0 else 0

            properties = {
                    "value": biomass_val,
                    "normalized_value": normalized_val,
                    "row": j,
                    "col": i
            }

            if mode == 'pm3d':
                    species_data = {}
                    for species_name, species_array in species_biomass_average.items():
                        species_val = float(species_array[j][i])
                        if species_val > 0:
                            species_data[species_name] = species_val

                    properties["species"] = species_data

            # Create feature
            feature = {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": polygon_coords},
                "properties": properties
            }

            features.append(feature)

    return {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "biomass_min": biomass_min,
            "biomass_max": biomass_max,
            "value_range": value_range
        }
    }

def get_center(feature):
    coords = feature["geometry"]["coordinates"][0]
    lons = [pt[0] for pt in coords]
    lats = [pt[1] for pt in coords]

    center_lon = (min(lons) + max(lons)) / 2
    center_lat = (min(lats) + max(lats)) / 2

    return (center_lon, center_lat)