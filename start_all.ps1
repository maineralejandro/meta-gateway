# Hermes WhatsApp Gateway - Windows Startup Script
# Este script automatiza el inicio de la API, el Dashboard y ngrok en Windows.

$WORKDIR = "C:\Mainer-AI\Hermes\meta-gateway"
$VENV_DIR = "$WORKDIR\win_venv"

Clear-Host
Write-Host "Hermes WhatsApp Gateway - Start All Services (Windows)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Verificar dependencias
Write-Host "[1/3] Verificando dependencias..." -ForegroundColor Gray
$pythonCmd = if (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { "python3" }
if (!(Get-Command $pythonCmd -ErrorAction SilentlyContinue)) { Write-Error "Python no está instalado"; exit }
if (!(Get-Command node -ErrorAction SilentlyContinue)) { Write-Error "Node no está instalado"; exit }
if (!(Get-Command npm -ErrorAction SilentlyContinue)) { Write-Error "NPM no está instalado"; exit }

# 2. Configurar entorno virtual
if (!(Test-Path $VENV_DIR)) {
    Write-Host "   -> Creando virtualenv en $VENV_DIR..." -ForegroundColor Yellow
    & $pythonCmd -m venv $VENV_DIR
    Write-Host "   -> Instalando dependencias de Python..." -ForegroundColor Yellow
    & "$VENV_DIR\Scripts\pip.exe" install -r "$WORKDIR\requirements.txt"
} else {
    Write-Host "   -> Entorno virtual OK" -ForegroundColor Green
}

# 3. Verificar dependencias del Dashboard
if (!(Test-Path "$WORKDIR\dashboard\node_modules")) {
    Write-Host "[2/3] Instalando dependencias del Dashboard..." -ForegroundColor Yellow
    Push-Location "$WORKDIR\dashboard"
    npm install
    Pop-Location
} else {
    Write-Host "[2/3] Dependencias del Dashboard OK" -ForegroundColor Green
}

# 4. Lanzar servicios en Windows Terminal
Write-Host "[3/3] Lanzando servicios en Windows Terminal..." -ForegroundColor Cyan

# Para Windows Terminal, los punto y coma internos de un comando deben escaparse con \
# de lo contrario WT los interpreta como separadores de sus propios comandos.
$API_CMD = "Write-Host '--- API FASTAPI ---' -ForegroundColor Cyan\; . .\win_venv\Scripts\activate\; uvicorn main:app --reload --host 0.0.0.0 --port 8080"
$DASH_CMD = "Write-Host '--- DASHBOARD ---' -ForegroundColor Green\; npm run dev"
$NGROK_CMD = "Write-Host '--- NGROK / WEBHOOK ---' -ForegroundColor Yellow\; if (Get-Command ngrok -ErrorAction SilentlyContinue) { ngrok http 8080 } else { Write-Warning 'ngrok no está instalado.' }"

if (Get-Command wt -ErrorAction SilentlyContinue) {
    # Combinamos los comandos usando el separador de WT (;)
    # Nota: No dejamos espacios alrededor de los ';' de WT para evitar problemas de rutas
    $wtArgs = "-d `"$WORKDIR`" powershell.exe -NoExit -Command `"$API_CMD`""
    $wtArgs += ";split-pane -H -d `"$WORKDIR\dashboard`" powershell.exe -NoExit -Command `"$DASH_CMD`""
    $wtArgs += ";split-pane -V -d `"$WORKDIR`" powershell.exe -NoExit -Command `"$NGROK_CMD`""
    
    Start-Process wt -ArgumentList $wtArgs
} else {
    Write-Warning "Windows Terminal (wt.exe) no encontrado. Se abrirán ventanas separadas."
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location $WORKDIR; . .\win_venv\Scripts\activate; uvicorn main:app --reload --host 0.0.0.0 --port 8080"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location $WORKDIR\dashboard; npm run dev"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location $WORKDIR; if (Get-Command ngrok -ErrorAction SilentlyContinue) { ngrok http 8080 } else { pause }"
}

Write-Host "`n¡TODO INICIADO!" -ForegroundColor Green
Write-Host "--------------------------------------------------------"
Write-Host "Dashboard:  http://localhost:3000" -ForegroundColor White
Write-Host "API Docs:   http://localhost:8080/docs" -ForegroundColor White
Write-Host "Webhook:    http://localhost:8080/webhook/whatsapp" -ForegroundColor White
Write-Host "--------------------------------------------------------"
Write-Host "Próximo paso: Configura la URL de ngrok en el portal de Meta Developers."
