# 자막 자동 생성 — 설치 스크립트 (Windows 10/11)
# 필요한 것: 인터넷 연결, 약 2.5GB 여유 공간
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = $PSScriptRoot
Set-Location $Root
# 기존 '자막생성툴'이 쓰는 공용 폴더. 읽기(복사)만 하고 절대 수정하지 않는다.
$OldRuntime = Join-Path $(if ($env:PUBLIC) { $env:PUBLIC } else { "C:\Users\Public" }) "Documents\SubtitleToolRuntime"

function Step($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }
function Download($url, $dest) {
    if (Test-Path $dest) { Write-Host "  이미 있음: $(Split-Path $dest -Leaf)"; return }
    New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
    Write-Host "  다운로드: $(Split-Path $dest -Leaf)"
    & curl.exe -L --fail --retry 5 --retry-delay 3 -C - -o "$dest.part" $url
    if ($LASTEXITCODE -ne 0) { throw "다운로드 실패: $url" }
    Move-Item -Force "$dest.part" $dest
}

# 1. Python ------------------------------------------------------------
Step "1/5 Python 환경"
$py = $null
foreach ($cand in @("py -3.12", "py -3.11", "py -3.13", "python")) {
    $parts = $cand.Split(" "); $exe = $parts[0]; $rest = @($parts | Select-Object -Skip 1)
    try {
        $v = & $exe @rest -c "import sys,tkinter;print('%d.%d'%sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { $py = $cand; Write-Host "  사용: $cand (Python $v)"; break }
    } catch {}
}
if (-not $py) {
    Write-Host "  Python이 없어 설치합니다 (winget)..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $py = "py -3.12"
}
$parts = $py.Split(" "); $pyExe = $parts[0]; $pyArgs = @($parts | Select-Object -Skip 1)
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & $pyExe @pyArgs -m venv .venv
}
& .venv\Scripts\python.exe -m pip install --upgrade pip -q
& .venv\Scripts\python.exe -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { throw "pip 설치 실패" }

# 2. FFmpeg ------------------------------------------------------------
Step "2/5 FFmpeg"
$existingFF = @(
    (Get-ChildItem "$OldRuntime\FFmpeg" -Recurse -Filter ffmpeg.exe -Depth 4 -ErrorAction SilentlyContinue | Select-Object -First 1).FullName,
    (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not (Test-Path "tools\ffmpeg.exe") -and $existingFF) {
    Write-Host "  이미 설치된 FFmpeg를 복사해서 사용: $existingFF" -ForegroundColor Green
    New-Item -ItemType Directory -Force tools | Out-Null
    Copy-Item "$(Split-Path $existingFF)\*" tools\ -Include *.exe,*.dll
}
if (-not (Test-Path "tools\ffmpeg.exe")) {
    $zip = "$env:TEMP\ffmpeg-essentials.zip"
    Download "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $zip
    $tmp = "$env:TEMP\ffmpeg-x"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive $zip $tmp
    New-Item -ItemType Directory -Force tools | Out-Null
    Copy-Item (Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName tools\ffmpeg.exe
    Remove-Item -Recurse -Force $tmp, $zip
} else { Write-Host "  이미 있음" }

# 3. whisper.cpp -------------------------------------------------------
Step "3/5 whisper.cpp 엔진"
$vk = Get-ChildItem $Root -Filter "whisper-vulkan-x64*.zip" | Select-Object -First 1
$dst = "engines\whisper"
if ($vk) {
    Write-Host "  Vulkan(GPU) 빌드 사용: $($vk.Name)" -ForegroundColor Green
    $src = $vk.FullName
} elseif (-not (Test-Path "$dst\whisper-cli.exe") -and ($oldVk = @(
        "$OldRuntime\WhisperCppSource\build-vulkan\bin\Release\whisper-cli.exe",
        "$OldRuntime\WhisperCppSource\build-vulkan\bin\whisper-cli.exe",
        "C:\whisper.cpp\build-vulkan\bin\Release\whisper-cli.exe",
        "C:\whisper.cpp\build-vulkan\bin\whisper-cli.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1)) {
    Write-Host "  이미 PC에 빌드된 Vulkan whisper-cli를 복사해서 사용: $oldVk" -ForegroundColor Green
    New-Item -ItemType Directory -Force $dst | Out-Null
    Copy-Item "$(Split-Path $oldVk)\*" $dst -Include *.exe,*.dll
    $src = $null
} elseif (-not (Test-Path "$dst\whisper-cli.exe")) {
    Write-Host "  whisper-vulkan-x64.zip 이 없어 공식 CPU 빌드를 받습니다." -ForegroundColor Yellow
    Write-Host "  (GPU 가속을 쓰려면 README의 'Vulkan 빌드 받기'를 참고하세요)"
    $src = "$env:TEMP\whisper-bin-x64.zip"
    Download "https://github.com/ggml-org/whisper.cpp/releases/latest/download/whisper-bin-x64.zip" $src
} else { $src = $null; Write-Host "  이미 있음" }
if ($src) {
    $tmp = "$env:TEMP\whisper-x"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive $src $tmp
    $cli = Get-ChildItem $tmp -Recurse -Filter whisper-cli.exe | Select-Object -First 1
    if (-not $cli) { throw "zip 안에 whisper-cli.exe가 없습니다: $src" }
    Remove-Item -Recurse -Force $dst -ErrorAction SilentlyContinue
    New-Item -ItemType Directory -Force $dst | Out-Null
    Copy-Item "$($cli.DirectoryName)\*" $dst -Recurse
    Remove-Item -Recurse -Force $tmp
}

# 4. 모델 --------------------------------------------------------------
Step "4/5 Whisper 모델 (large-v3-turbo Q8_0, 약 0.9GB)"
Download "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q8_0.bin" "models\ggml-large-v3-turbo-q8_0.bin"

Step "5/5 Parakeet 모델 (교차검증용, 약 0.65GB)"
$pk = "models\parakeet-tdt-0.6b-v2-int8"
$hf = "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main"
foreach ($f in @("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")) {
    Download "$hf/$f" "$pk\$f"
}

# 점검 -----------------------------------------------------------------
Step "점검"
& "engines\whisper\whisper-cli.exe" --help *> $null
if ($LASTEXITCODE -ne 0) { Write-Host "  whisper-cli 실행 실패 (Visual C++ 재배포 패키지가 필요할 수 있음)" -ForegroundColor Red }
else { Write-Host "  whisper-cli OK" }
& .venv\Scripts\python.exe -c "import sherpa_onnx, numpy, tkinter; print('  Python 패키지 OK')"

Write-Host ""
Write-Host "설치 완료! '자막만들기.bat'을 실행하세요." -ForegroundColor Green
