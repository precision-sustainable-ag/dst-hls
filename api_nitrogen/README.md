# Plant API

This API provides information about plant species, plant groups, plant growth stages, and plant factors based on a provided plant species and growth stage.

## Endpoints

### GET /

- Description: Check the health status of the API.
- Response:
  ```json
  {"health": "ok"}
  ```

### GET /species

- Description: Get a list of plant species.
- Response:
  ```json
  {
    "species_name_1": ["variety_1", "variety_2", ...],
    "species_name_2": ["variety_1", "variety_2", ...],
    ...
  }
  ```

### GET /plantgroups

- Description: Get a list of plant groups.
- Response:
  ```json
  ["plant_group_1", "plant_group_2", ...]
  ```

### GET /plantgrowthstages

- Description: Get a list of plant growth stages.
- Response:
  ```json
  ["growth_stage_1", "growth_stage_2", ...]
  ```

### GET /plantfactors

- Description: Get a lookup table of plant factors.
- Response:
  ```json
  {
    "plant_specie_1": {
      "growth_stage_1": {
        "factor_1": value_1,
        "factor_2": value_2,
        ...
      },
      "growth_stage_2": {
        "factor_1": value_1,
        "factor_2": value_2,
        ...
      },
      ...
    },
    "plant_specie_2": {
      ...
    },
    ...
  }
  ```

### GET /plantfactors/{plant_specie}/{growth_stage}

- Description: Get factors for a specific plant species and growth stage.
- Parameters:
  - `plant_specie`: The name of the plant species.
  - `growth_stage`: The growth stage of the plant.
- Response: Factors for the specified plant species and growth stage.
  
## Usage

### Getting Started

To get started with the API, follow these steps:

1. Ensure you have Python installed on your system.
2. Clone this repository.
3. Install the required dependencies using `pip install -r requirements.txt`.
4. Run the API using `uvicorn main:app --reload`.
5. Access the API at `http://localhost:8000`.

## Example

### Request

```http
GET /plantfactors/wheat/stemming
```

### Response

```json
{
"nitrogen_percentage":2.26, "carbohydrates_percentage":52.39, "holo_cellulose_percentage":23.95, "lignin_cellulose_percentage":9.19
}
```

## Dependencies

- `fastapi`: A modern, fast (high-performance), web framework for building APIs with Python 3.7+.
- `uvicorn`: A lightning-fast ASGI server implementation, using uvloop and httptools.
- `typing`: This module provides runtime support for type hints. (Included in Python 3.5+)


## Note

- Ensure that the provided plant species and growth stages are valid. Otherwise, a 404 status code will be returned along with an error message.
- The data for plant factors is loaded from a JSON file named `plant_growth_lut.json` located in the `app/assets/` directory. Make sure the file exists and is properly formatted.

