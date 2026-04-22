#!/bin/zsh

# sudo chown -R vscode:vscode node_modules
sudo chown -R vscode:vscode .venv
# bun install --frozen-lockfile --ignore-scripts

# Fetch YaneuraOu source (vendor/YaneuraOu). Engine binaries are NOT built
# here — run ./scripts/build_yaneuraou.sh <variant> on demand.
git submodule update --init --recursive
