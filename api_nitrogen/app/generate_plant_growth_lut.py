import os
import json
import random
import numpy as np
from pprint import pprint
from constants import species, plant_groups, plant_growth_stages

nitrogen_percentage_range = [0, 6]
carbohydrates_percentage_range = [20, 70]
holo_cellulose_percentage_range = [20, 70]
lignin_percentage_range = [1, 10]

lut = {}
for plant_group in plant_growth_stages:
  stages = plant_growth_stages[plant_group]
  for specie in species[plant_group]:
    specie = specie.lower()
    lut[specie.lower()] = {}
    for stage in stages:
      stage = stage.lower()
      factors = {
        'nitrogen_percentage': round(random.uniform(*nitrogen_percentage_range),2),
        'carbohydrates_percentage': round(random.uniform(*carbohydrates_percentage_range),2),
        'holo_cellulose_percentage': round(random.uniform(*holo_cellulose_percentage_range),2),
        'lignin_cellulose_percentage': round(random.uniform(*lignin_percentage_range),2),
      }
      lut[specie][stage] = factors
    
with open('./assets/plant_growth_lut.json', 'w') as fp:
    json.dump(lut, fp)
    
pprint(lut)
