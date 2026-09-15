#!/bin/bash

echo "=========================================================="
echo "  🚀 Starting YouTube Multilingual Video Transcript Chatbot"
echo "  Target: Qwen 2.5 AI + Ollama / RAG Architecture"
echo "=========================================================="

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR" || exit 1

# Create Python virtual environment if not present
if [ ! -d "venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv venv
fi

echo "⚡ Activating virtual environment & installing dependencies..."
source venv/bin/activate
pip install -q --upgrade pip
pip install -q -r backend/requirements.txt

# Check Ollama
if command -v ollama &> /dev/null; then
    echo "✅ Ollama CLI detected!"
    echo "💡 Reminder: Run 'ollama pull qwen2.5:3b' to download local Qwen AI model."
else
    echo "⚠️ Ollama CLI is not in PATH. You can install it via 'brew install ollama'."
    echo "   (The app will use the RAG Fallback & Free API mode automatically until Ollama is running)."
fi

# Free port 8000 if already in use by a previous process
echo "🧹 Ensuring port 8000 is free..."
lsof -ti :8000 | xargs kill -9 2>/dev/null || true

echo ""
echo "🌐 Starting FastAPI Server on http://localhost:8000 ..."
echo "=========================================================="
cd backend
python3 main.py
