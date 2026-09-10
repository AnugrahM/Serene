# SEREN STEP 1 - Whisper Vulkan setup
# Run from the MyAI project folder.
# This script uses ASCII-only text to avoid PowerShell 5.1 parsing issues.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ThirdParty = Join-Path $ProjectRoot "third_party"
$WhisperRoot = Join-Path $ThirdParty "whisper.cpp"
$BuildDir = Join-Path $WhisperRoot "build"
$ModelDir = Join-Path $ProjectRoot "models"
$ModelFile = Join-Path $ModelDir "ggml-large-v3-turbo-q8_0.bin"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

Write-Host ""
Write-Host "============================================================"
Write-Host "SEREN STEP 1 - WHISPER VULKAN SETUP"
Write-Host "============================================================"
Write-Host ""

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found. Install Git for Windows and reopen PowerShell."
}

if (-not (Get-Command cmake -ErrorAction SilentlyContinue)) {
    throw "CMake was not found. Install CMake and reopen PowerShell."
}

if (-not $env:VULKAN_SDK) {
    throw "VULKAN_SDK is not set. Install the Vulkan SDK, reopen PowerShell, and run this script again."
}

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    throw "cl.exe was not found. Use a Visual Studio Developer PowerShell or install Desktop development with C++."
}

if (-not (Test-Path $VenvPython)) {
    throw ".venv was not found at: $VenvPython"
}

Write-Host "Git       : OK"
Write-Host "CMake     : OK"
Write-Host "MSVC      : OK"
Write-Host "Vulkan SDK: $env:VULKAN_SDK"
Write-Host ""

Write-Host "[1/4] Installing Python packages..."

& $VenvPython -m pip install --upgrade pip

$PyPackages = @(
    "pywebrtc-audio",
    "av",
    "requests",
    "webrtcvad-wheels",
    "edge-tts",
    "sounddevice",
    "scipy",
    "numpy",
    "openwakeword"
)

& $VenvPython -m pip install @PyPackages

Write-Host ""
Write-Host "[2/4] Getting whisper.cpp..."

New-Item -ItemType Directory -Force -Path $ThirdParty | Out-Null

if (-not (Test-Path (Join-Path $WhisperRoot ".git"))) {
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git $WhisperRoot
}
else {
    git -C $WhisperRoot pull --ff-only
}

Write-Host ""
Write-Host "[3/4] Configuring and building whisper.cpp with Vulkan..."

$CMakeConfigure = @(
    "-S", $WhisperRoot,
    "-B", $BuildDir,
    "-DGGML_VULKAN=ON",
    "-DWHISPER_BUILD_SERVER=ON",
    "-DGGML_AVX512=OFF",
    "-DCMAKE_BUILD_TYPE=Release"
)

& cmake @CMakeConfigure

$CMakeBuild = @(
    "--build", $BuildDir,
    "--config", "Release",
    "-j", "8"
)

& cmake @CMakeBuild

Write-Host ""
Write-Host "[4/4] Downloading Whisper large-v3-turbo Q8_0..."

New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null

$ModelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q8_0.bin?download=true"

if (-not (Test-Path $ModelFile)) {
    & curl.exe `
        --location `
        --fail `
        --retry 5 `
        --retry-delay 3 `
        --continue-at - `
        --output $ModelFile `
        $ModelUrl
}
else {
    Write-Host "Model already exists."
}

$Server1 = Join-Path $BuildDir "bin\Release\whisper-server.exe"
$Server2 = Join-Path $BuildDir "bin\whisper-server.exe"

if (Test-Path $Server1) {
    $ServerPath = $Server1
}
elseif (Test-Path $Server2) {
    $ServerPath = $Server2
}
else {
    throw "whisper-server.exe was not found after the build."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "SETUP COMPLETE"
Write-Host "============================================================"
Write-Host "Whisper server:"
Write-Host $ServerPath
Write-Host ""
Write-Host "Whisper model:"
Write-Host $ModelFile
Write-Host ""
Write-Host "Next: run seren_v2.py"
Write-Host ""
