# Hermes WhatsApp Gateway - Windows Startup Script
# Este script automatiza el inicio de la API, el Dashboard y ngrok en Windows.

$WORKDIR = $PSScriptRoot
$VENV_DIR = "$WORKDIR\win_venv"

Clear-Host
Write-Host "Hermes WhatsApp Gateway - Start All Services (Windows)" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 0. Limpiar procesos anteriores (opcional pero recomendado)
Get-Process | Where-Object { $_.Name -match "uvicorn|ngrok" } | Stop-Process -Force -ErrorAction SilentlyContinue

# 1. Verificar dependencias
Write-Host "[1/3] Verificando dependencias..." -ForegroundColor Gray

# Intentar encontrar una versión de Python compatible (3.11 o 3.12)
$pythonExe = "python"
$pythonArgs = @()

if (Get-Command py -ErrorAction SilentlyContinue) {
    if (& py -3.12 --version 2>$null) { 
        $pythonExe = "py"
        $pythonArgs = @("-3.12") 
    }
    elseif (& py -3.11 --version 2>$null) { 
        $pythonExe = "py"
        $pythonArgs = @("-3.11") 
    }
}

if ($pythonExe -eq "python") {
    $version = & python --version
    if ($version -notmatch "3\.(11|12)") {
        if (Get-Command py -ErrorAction SilentlyContinue) { 
            $pythonExe = "py"
            $pythonArgs = @("-3.12") 
        }
    }
}

Write-Host "   -> Usando Python: $((& $pythonExe $pythonArgs --version))" -ForegroundColor Gray

if (!(Get-Command node -ErrorAction SilentlyContinue)) { Write-Error "Node no está instalado"; exit }
if (!(Get-Command npm -ErrorAction SilentlyContinue)) { Write-Error "NPM no está instalado"; exit }

# 2. Configurar entorno virtual
if (!(Test-Path $VENV_DIR)) {
    Write-Host "   -> Creando virtualenv en $VENV_DIR..." -ForegroundColor Yellow
    & $pythonExe $pythonArgs -m venv $VENV_DIR
    
    # Verificar si se creó correctamente
    if (Test-Path "$VENV_DIR\Scripts\pip.exe") {
        Write-Host "   -> Instalando dependencias de Python..." -ForegroundColor Yellow
        & "$VENV_DIR\Scripts\pip.exe" install -r "$WORKDIR\requirements.txt"
    } else {
        Write-Error "No se pudo crear el entorno virtual correctamente en $VENV_DIR"
        exit
    }
} else {
    Write-Host "   -> Entorno virtual OK" -ForegroundColor Green
}

# 3. Verificar dependencias del Dashboard
if (!(Test-Path "$WORKDIR\dashboard\node_modules\next")) {
    Write-Host "[2/3] Instalando dependencias del Dashboard (esto puede tardar)..." -ForegroundColor Yellow
    Push-Location "$WORKDIR\dashboard"
    # Forzar una limpieza si el usuario tuvo errores
    if (Test-Path "node_modules") { Remove-Item -Recurse -Force "node_modules" }
    npm install
    Pop-Location
} else {
    Write-Host "[2/3] Dependencias del Dashboard OK" -ForegroundColor Green
}

# 4. Leer .env y exportar variables clave como env vars (bypass WSL2 9p cache bug)
Write-Host "[3/4] Leyendo configuracion del .env..." -ForegroundColor Gray
$envFile = Get-Content "$WORKDIR\.env" -ErrorAction SilentlyContinue
$envMap = @{}
foreach ($line in $envFile) {
    if ($line -match '^\s*([^#][^=]+)=(.*)$') {
        $envMap[$Matches[1].Trim()] = $Matches[2].Trim()
    }
}
$env:WHATSAPP_ACCESS_TOKEN = $envMap['WHATSAPP_ACCESS_TOKEN']
Write-Host " -> WHATSAPP_ACCESS_TOKEN set (${ $($env:WHATSAPP_ACCESS_TOKEN.Length) } chars)" -ForegroundColor Gray

# 5. Lanzar servicios en Windows Terminal
Write-Host "[4/4] Lanzando servicios en Windows Terminal..." -ForegroundColor Cyan

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
