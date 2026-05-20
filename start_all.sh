#!/bin/bash

echo "Hermes WhatsApp Gateway - Start All Services"
echo "=============================================="

check_installed() {
    if ! command -v $1 &> /dev/null; then
        echo "ERROR: $1 no esta instalado"
        exit 1
    fi
    echo "  OK: $1"
}

echo "Verificando dependencias..."
check_installed python3
check_installed node
check_installed npm
check_installed tmux

WORKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$WORKDIR/.venv"

if [ ! -f "$WORKDIR/main.py" ]; then
    echo "ERROR: main.py no existe en $WORKDIR"
    exit 1
fi

if [ ! -f "$WORKDIR/dashboard/package.json" ]; then
    echo "ERROR: dashboard/package.json no existe"
    exit 1
fi

echo "Verificando que Supabase local este corriendo..."
if ! docker ps --filter "name=supabase_db_app" --format '{{.Names}}' | grep -q supabase_db_app; then
    echo "ERROR: Supabase local no esta corriendo. Ejecuta 'supabase start' primero."
    exit 1
fi
echo " OK: Supabase local listo (localhost:54322)"

if [ ! -d "$VENV_DIR" ]; then
    echo "Creando virtualenv en $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
    echo "Instalando dependencias Python..."
    source "$VENV_DIR/bin/activate"
    pip install -r "$WORKDIR/requirements.txt" -q
else
    source "$VENV_DIR/bin/activate"
    echo "  Venv OK: $VENV_DIR"
fi

if [ ! -d "$WORKDIR/dashboard/node_modules" ]; then
    echo "Instalando dependencias Dashboard..."
    cd "$WORKDIR/dashboard"
    npm install
    cd "$WORKDIR"
else
    echo "  Dashboard deps OK: node_modules existe"
fi

pkill -f "uvicorn main:app" 2>/dev/null || true
tmux kill-session -t whatsapp-gateway 2>/dev/null || true
sleep 1

tmux new-session -d -s whatsapp-gateway -x 300 -y 80

PANE0=$(tmux list-panes -t whatsapp-gateway -F '#{pane_id}' | head -1)

tmux send-keys -t $PANE0 "cd $WORKDIR && source $VENV_DIR/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8080" C-m
sleep 3

tmux split-window -h -t $PANE0
PANE1=$(tmux list-panes -t whatsapp-gateway -F '#{pane_id}' | tail -1)

tmux send-keys -t $PANE1 "cd $WORKDIR/dashboard && npm run dev" C-m
sleep 2

tmux split-window -v -t $PANE0
PANE2=$(tmux list-panes -t whatsapp-gateway -F '#{pane_id}' | tail -1)

tmux send-keys -t $PANE2 "ngrok http 8080" C-m

echo ""
echo "TODO INICIADO!"
echo ""
echo "tmux attach -t whatsapp-gateway"
echo ""
echo "  Dashboard: http://localhost:3000"
echo "  API Docs:  http://localhost:8080/docs"
echo "  Webhook:   http://localhost:8080/webhook/whatsapp"
echo "  Health:    http://localhost:8080/api/health"
echo " Postgres: localhost:54322 (Supabase)"
echo ""
echo "Proximo paso: Configura el webhook en Meta Developer Dashboard"
echo "  1. Copia la URL de ngrok del panel inferior izquierdo"
echo "  2. Ve a WhatsApp > Configuration > Edit webhook URL"
echo "  3. Pega: {ngrok_url}/webhook/whatsapp"
echo "  4. Verify token: comida_rapida_secret_2024"
echo "  5. Subscribir a: messages"
