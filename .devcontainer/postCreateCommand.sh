#!/bin/zsh

sudo chown -R vscode:vscode node_modules
sudo chown -R vscode:vscode .venv
bun install --frozen-lockfile --ignore-scripts
