# SEREN DIAGNOSTIC - Phase 1
# Run this file from anywhere:
#   powershell -ExecutionPolicy Bypass -File .\seren_diagnose.ps1
#
# It does NOT install, uninstall, or modify anything.

$ErrorActionPreference = "Continue"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ThirdParty = Join-Path $ProjectRoot "third_party"
$WhisperRoot = Join-Path $ThirdParty "whisper.cpp"
$ModelFile = Join-Path $ProjectRoot "models\ggml-large-v3-turbo-q8_0.bin"

Write-Host ""
Write-Host "============================================================"
Write-Host "SEREN - PHASE 1 HARDWARE / BACKEND DIAGNOSTIC"
Write-Host "============================================================"
Write-Host "Project root: $ProjectRoot"
Write-Host ""

# ------------------------------------------------------------
# CPU / GPU
# ------------------------------------------------------------
Write-Host "[1] CPU / GPU"
try {
    Get-CimInstance Win32_Processor |
        Select-Object Name |
        Format-Table -AutoSize
}
catch {
    Write-Host "CPU query failed: $($_.Exception.Message)"
}

try {
    Get-CimInstance Win32_VideoController |
        Select-Object Name, AdapterRAM, DriverVersion |
        Format-Table -AutoSize
}
catch {
    Write-Host "GPU query failed: $($_.Exception.Message)"
}

# ------------------------------------------------------------
# Ollama
# ------------------------------------------------------------
Write-Host "[2] OLLAMA"

$ollama = Get-Command ollama -ErrorAction SilentlyContinue

if (-not $ollama) {
    Write-Host "OLLAMA: NOT FOUND on PATH"
}
else {
    Write-Host "Ollama executable: $($ollama.Source)"

    Write-Host ""
    Write-Host "--- ollama --version ---"
    & ollama --version

    Write-Host ""
    Write-Host "--- ollama list ---"
    & ollama list

    Write-Host ""
    Write-Host "--- ollama ps ---"
    & ollama ps
}

# ------------------------------------------------------------
# Ollama / local server check
# ------------------------------------------------------------
Write-Host ""
Write-Host "[3] OLLAMA LOCAL SERVER"

try {
    $response = Invoke-WebRequest `
        -Uri "http://127.0.0.1:11434/api/tags" `
        -TimeoutSec 2 `
        -UseBasicParsing

    Write-Host "Ollama API: ONLINE"
}
catch {
    Write-Host "Ollama API: OFFLINE"
}

# ------------------------------------------------------------
# Current process environment
# ------------------------------------------------------------
Write-Host ""
Write-Host "[4] SEREN OLLAMA ENVIRONMENT"

foreach ($name in @(
    "OLLAMA_VULKAN",
    "OLLAMA_IGPU_ENABLE",
    "OLLAMA_LLM_LIBRARY",
    "GGML_VK_VISIBLE_DEVICES"
)) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    if ([string]::IsNullOrWhiteSpace($value)) {
        Write-Host "$name = <not set>"
    }
    else {
        Write-Host "$name = $value"
    }
}

# ------------------------------------------------------------
# Vulkan SDK / Vulkan runtime
# ------------------------------------------------------------
Write-Host ""
Write-Host "[5] VULKAN"

if ($env:VULKAN_SDK) {
    Write-Host "VULKAN_SDK = $env:VULKAN_SDK"
}
else {
    Write-Host "VULKAN_SDK = <not set>"
    Write-Host "This is expected until the Vulkan development SDK is installed."
}

$vulkanInfo = Get-Command vulkaninfo -ErrorAction SilentlyContinue

if ($vulkanInfo) {
    Write-Host ""
    Write-Host "--- vulkaninfo --summary ---"
    & vulkaninfo --summary 2>$null
}
else {
    Write-Host "vulkaninfo = NOT FOUND"
}

# ------------------------------------------------------------
# Whisper build artifacts
# ------------------------------------------------------------
Write-Host ""
Write-Host "[6] WHISPER.CPP BUILD"

if (-not (Test-Path $WhisperRoot)) {
    Write-Host "Whisper source folder: NOT FOUND"
}
else {
    Write-Host "Whisper source folder: FOUND"

    $servers = Get-ChildItem `
        -Path $WhisperRoot `
        -Filter "whisper-server.exe" `
        -Recurse `
        -File `
        -ErrorAction SilentlyContinue

    if ($servers.Count -eq 0) {
        Write-Host "whisper-server.exe: NOT FOUND"
    }
    else {
        Write-Host "whisper-server.exe:"
        $servers | ForEach-Object {
            Write-Host "  $($_.FullName)"
        }
    }

    $vulkanDlls = Get-ChildItem `
        -Path $WhisperRoot `
        -Filter "ggml-vulkan.dll" `
        -Recurse `
        -File `
        -ErrorAction SilentlyContinue

    if ($vulkanDlls.Count -eq 0) {
        Write-Host "ggml-vulkan.dll: NOT FOUND"
        Write-Host "A Vulkan-enabled whisper.cpp build is therefore not confirmed."
    }
    else {
        Write-Host "ggml-vulkan.dll: FOUND"
        $vulkanDlls | ForEach-Object {
            Write-Host "  $($_.FullName)"
        }
    }
}

# ------------------------------------------------------------
# Whisper model
# ------------------------------------------------------------
Write-Host ""
Write-Host "[7] WHISPER MODEL"

if (Test-Path $ModelFile) {
    $sizeGB = (Get-Item $ModelFile).Length / 1GB
    Write-Host ("Model FOUND: {0} ({1:N2} GB)" -f $ModelFile, $sizeGB)
}
else {
    Write-Host "Model NOT FOUND: $ModelFile"
}

# ------------------------------------------------------------
# Python environment
# ------------------------------------------------------------
Write-Host ""
Write-Host "[8] PYTHON ENVIRONMENT"

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (Test-Path $VenvPython) {
    Write-Host "Virtual environment: FOUND"
    & $VenvPython --version

    Write-Host ""
    Write-Host "--- important Python packages ---"
    foreach ($pkg in @(
        "numpy",
        "requests",
        "edge-tts",
        "av",
        "sounddevice",
        "webrtcvad-wheels",
        "pywebrtc-audio",
        "openwakeword"
    )) {
        & $VenvPython -m pip show $pkg 2>$null |
            Select-String "^(Name|Version):"
    }
}
else {
    Write-Host "Virtual environment NOT FOUND: $VenvPython"
}

Write-Host ""
Write-Host "============================================================"
Write-Host "DIAGNOSTIC COMPLETE"
Write-Host "============================================================"
Write-Host ""
Write-Host "Paste the ENTIRE output back here."
Write-Host "This script did not install or change anything."
Write-Host ""
