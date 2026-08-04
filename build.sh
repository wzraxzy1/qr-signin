#!/bin/bash
set -e

echo "=== Installing Python dependencies ==="
cd backend
pip install -r requirements.txt
cd ..

echo "=== Installing Node.js dependencies ==="
cd frontend
npm install
cd ..

echo "=== Building React frontend ==="
cd frontend
npm run build
cd ..

echo "=== Build complete ==="
