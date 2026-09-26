#!/bin/bash
export PYTHONPATH="$(pwd -W)/src"
bash tools/gate.sh py
