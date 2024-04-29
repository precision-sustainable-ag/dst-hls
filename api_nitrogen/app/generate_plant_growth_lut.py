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
      n_ = random.uniform(*nitrogen_percentage_range)
      c_ = random.uniform(*carbohydrates_percentage_range)
      h_ = random.uniform(*holo_cellulose_percentage_range)
      l_ = random.uniform(*lignin_percentage_range)
      
      n__ = n_/(n_+c_+h_+l_)
      c__ = c_/(n_+c_+h_+l_)
      h__ = h_/(n_+c_+h_+l_)
      l__ = l_/(n_+c_+h_+l_)
      
      n = np.round(np.floor(n__*10000)/100, 2)
      h = np.round(np.floor(h__*10000)/100, 2)
      l = np.round(np.floor(l__*10000)/100, 2)
      c = np.round(10000 - (n+h+l)*100)/100
      
      print(n+c+h+l, n,c,h,l, specie, stage)
      factors = {
        'nitrogen_percentage': n,
        'carbohydrates_percentage': c,
        'holo_cellulose_percentage': h,
        'lignin_percentage': l,
      }
      lut[specie][stage] = factors
    
with open('./assets/plant_growth_lut.json', 'w') as fp:
    json.dump(lut, fp)
    
# pprint(lut)
