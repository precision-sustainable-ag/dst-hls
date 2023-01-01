#!/bin/bash
# poetry add pdoc3
mkdir $(pwd)/docs
pdoc --html $(pwd) --output-dir $(pwd)/docs --force
pdoc --http :8001 dst_hls