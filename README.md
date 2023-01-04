## HLS Satellite Data Toolbox 
This repo provides functionality to authenticate, fetch and preprocess satellite images from HLS LPDAAC server.


### Installation

- create a venv py3 environment

- install [poetry](https://python-poetry.org/docs/) if needed

- install packages via poetry
``` bash
poetry install
```


### Authentication

create .env file in the root dir

    .env:
        TEMP_CRED_URL = https://data.lpdaac.earthdatacloud.nasa.gov/s3credentials
        STAC_URL = https://cmr.earthdata.nasa.gov/stac
        NASA_PASS = <NASA_PASS>
        NASA_MACHINE = urs.earthdata.nasa.gov
        NASA_LOGIN = <NASA_USER>

    
### Quick Start
```python
from dst_hls import interface
geom_path = "<path to geojson geometry>"

field = geopandas.read_file(geom_path)
features = json.loads(field.to_json())["features"]
roi = features[0]["geometry"]
roi = json.dumps(roi)
    
infc = interface()
arr = infc.ndvi_images(roi, date_range="2021-07-01/2021-08-02")
```
