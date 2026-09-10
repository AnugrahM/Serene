# SEREN PHASE 2 - Build Whisper.cpp with Vulkan
# Run this from the MyAI project folder.
# This does not modify your Seren Python files.

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ThirdParty = Join-Path $ProjectRoot "third_party"
$WhisperRoot = Join-Path $ThirdParty "whisper.cpp"
$BuildDir = Join-Path $WhisperRoot "build"
$ModelDir = Join-Path $ProjectRoot "models"
$ModelFile = Join-Path $ModelDir "ggml-large-v3-turbo-q8_0.bin"

Write-Host ""
Write-Host "============================================================"
Write-Host "SEREN PHASE 2 - WHISPER + VULKAN"
Write-Host "============================================================"
Write-Host ""

# Tools
foreach ($tool in @("git", "cmake", "curl.exe")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool was not found on PATH. Install it or use a developer terminal, then reopen PowerShell."
    }
}

if (-not $env:VULKAN_SDK) {
    $candidate = Get-ChildItem "C:\VulkanSDK" -Directory -ErrorAction SilentlyContinue |
        Sort-Object Name -Descending |
        Select-Object -First 1

    if ($candidate) {
        $env:VULKAN_SDK = $candidate.FullName
        Write-Host "Using Vulkan SDK: $env:VULKAN_SDK"
    }
    else {
        throw "VULKAN_SDK is not set and no C:\VulkanSDK installation was found."
    }
}
else {
    Write-Host "Using Vulkan SDK: $env:VULKAN_SDK"
}

if (-not (Get-Command cl.exe -ErrorAction SilentlyContinue)) {
    throw "cl.exe was not found. Open 'Developer PowerShell for Visual Studio' and run this script there."
}

Write-Host "Git: OK"
Write-Host "CMake: OK"
Write-Host "MSVC cl.exe: OK"
Write-Host "Vulkan SDK: OK"

# Source
New-Item -ItemType Directory -Force -Path $ThirdParty | Out-Null

if (-not (Test-Path (Join-Path $WhisperRoot ".git"))) {
    Write-Host ""
    Write-Host "[1/3] Cloning whisper.cpp..."
    git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git $WhisperRoot
}
else {
    Write-Host ""
    Write-Host "[1/3] whisper.cpp already exists. Updating..."
    git -C $WhisperRoot pull --ff-only
}

# Build
Write-Host ""
Write-Host "[2/3] Building whisper.cpp with Vulkan..."

$configure = @(
    "-S", $WhisperRoot,
    "-B", $BuildDir,
    "-DGGML_VULKAN=ON",
    "-DWHISPER_BUILD_SERVER=ON",
    "-DWHISPER_BUILD_EXAMPLES=OFF",
    "-DWHISPER_BUILD_TESTS=OFF",
    "-DGGML_AVX512=OFF",
    "-DCMAKE_BUILD_TYPE=Release"
)

& cmake @configure
if ($LASTEXITCODE -ne 0) {
    throw "CMake configuration failed."
}

$build = @(
    "--build", $BuildDir,
    "--config", "Release",
    "-j", "8"
)

& cmake @build
if ($LASTEXITCODE -ne 0) {
    throw "Whisper build failed."
}

# Model
Write-Host ""
Write-Host "[3/3] Checking Whisper model..."

New-Item -ItemType Directory -Force -Path $ModelDir | Out-Null

if (-not (Test-Path $ModelFile)) {
    $ModelUrl = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q8_0.bin?download=true"

    curl.exe `
        --location `
        --fail `
        --retry 5 `
        --retry-delay 3 `
        --continue-at - `
        --output $ModelFile `
        $ModelUrl

    if ($LASTEXITCODE -ne 0) {
        throw "Whisper model download failed."
    }
}
else {
    Write-Host "Whisper model already exists."
}

$server = Join-Path $BuildDir "bin\Release\whisper-server.exe"
if (-not (Test-Path $server)) {
    $server = Join-Path $BuildDir "bin\whisper-server.exe"
}

$vk = Get-ChildItem $BuildDir -Filter "ggml-vulkan.dll" -Recurse -File -ErrorAction SilentlyContinue |
    Select-Object -First 1

if (-not (Test-Path $server)) {
    throw "whisper-server.exe was not produced."
}

if (-not $vk) {
    throw "ggml-vulkan.dll was not produced. Vulkan backend was not built."
}

Write-Host ""
Write-Host "============================================================"
Write-Host "WHISPER VULKAN BUILD COMPLETE"
Write-Host "============================================================"
Write-Host "Server : $server"
Write-Host "Vulkan : $($vk.FullName)"
Write-Host "Model  : $ModelFile"
Write-Host ""
Write-Host "Next test:"
Write-Host "  & '$server' --help"
Write-Host ""
