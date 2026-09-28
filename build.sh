#!/usr/bin/env bash
# ==============================================================================
# XYNAPSE // Render Build Script (Python + Vite React Frontend)
# ==============================================================================
set -o errexit

echo "[*] Upgrading pip and installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo "[*] Building React frontend production bundle..."
cd frontend
npm install
npm run build
cd ..

echo "[*] Build successful! Ready for uvicorn launch."
