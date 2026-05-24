#!/bin/bash

rm -rf src/*.egg-info
find src/ -type d -name "__pycache__" -exec rm -rf {} +
