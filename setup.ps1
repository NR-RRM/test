# 자막 자동 생성 — 설치 스크립트 (Windows 10/11)
# 필요한 것: 인터넷 연결, 약 2.5GB 여유 공간
#
# 기존 '자막생성툴'이 설치된 PC / 없는 PC 모두 지원:
#   - 있으면: 기존 공용 폴더에서 FFmpeg, Vulkan whisper-cli를 "실행 확인 후" 복사해서 사용 (원본은 읽기만 함)
#   - 없거나 기존 것이 동작하지 않으면: 새로 다운로드
# 이 스크립트는 프로그램 폴더 밖의 어떤 파일·PATH·레지스트리도 수정하지 않는다.
# (예외: Python이 전혀 없을 때만 winget으로 사용자 영역에 Python 3.12 설치)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = $PSScriptRoot
Set-Location $Root
$PublicDir = if ($env:PUBLIC) { $env:PUBLIC } else { "C:\Users\Public" }
$OldRuntime = Join-Path $PublicDir "Documents\SubtitleToolRuntime"

function Step($msg) { Write-Host ""; Write-Host "== $msg" -ForegroundColor Cyan }

function Download($url, $dest) {
    if (Test-Path $dest) { Write-Host "  이미 있음: $(Split-Path $dest -Leaf)"; return }
    New-Item -ItemType Directory -Force (Split-Path $dest) | Out-Null
    Write-Host "  다운로드: $(Split-Path $dest -Leaf)"
    & curl.exe -L --fail --retry 5 --retry-delay 3 -C - -o "$dest.part" $url
    if ($LASTEXITCODE -ne 0) { throw "다운로드 실패: $url" }
    Move-Item -Force "$dest.part" $dest
}

function Test-Exe($exe, [string[]]$arguments, $mustContain) {
    # 파일이 있는 것만으로는 부족: 실제 실행해서 기대한 출력이 나오는지 확인
    # (DLL 누락, chocolatey 등의 래퍼(shim), 너무 오래된 버전을 걸러냄)
    if (-not $exe -or -not (Test-Path $exe)) { return $false }
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = (& $exe @arguments 2>&1 | Out-String)
        return ($out -match $mustContain)
    } catch {
        return $false
    } finally {
        $ErrorActionPreference = $prev
    }
}

# 1. Python ------------------------------------------------------------
Step "1/5 Python 환경"
$lp = "$env:LOCALAPPDATA\Programs\Python"
$pyCands = @("py|-3.12", "py|-3.11", "py|-3.13",
             "$lp\Python312\python.exe", "$lp\Python311\python.exe", "$lp\Python313\python.exe",
             "python")

function Find-Python {
    foreach ($cand in $pyCands) {
        $parts = $cand.Split("|"); $exe = $parts[0]; $rest = @($parts | Select-Object -Skip 1)
        $ok = Test-Exe (Get-Command $exe -ErrorAction SilentlyContinue).Source `
                       ($rest + @("-c", "import sys,tkinter;print('PYOK',sys.version_info[1])")) "PYOK 1[1-3]"
        if ($ok) { Write-Host "  사용: $($cand.Replace('|', ' '))"; return $cand }
    }
    return $null
}

$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Exe $venvPy @("-c", "import tkinter;print('VENVOK')") "VENVOK")) {
    # .venv가 없거나, 만들 때 쓴 Python이 지워져서 깨진 경우 새로 만든다
    $py = Find-Python
    if (-not $py) {
        Write-Host "  사용할 수 있는 Python(3.11~3.13, tkinter 포함)이 없어 설치합니다..." -ForegroundColor Yellow
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "winget이 없습니다. https://www.python.org/downloads/ 에서 Python 3.12를 설치한 뒤 setup.bat을 다시 실행하세요."
        }
        winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
        $py = Find-Python   # 새로 설치한 Python은 현재 창 PATH에 없으므로 설치 경로로 찾음
        if (-not $py) { throw "Python 설치 후에도 찾지 못했습니다. 이 창을 닫고 setup.bat을 다시 실행하세요." }
    }
    if (Test-Path ".venv") { Remove-Item -Recurse -Force ".venv" }   # 프로그램 폴더 안의 깨진 venv만 삭제
    $parts = $py.Split("|"); $exe = $parts[0]; $rest = @($parts | Select-Object -Skip 1)
    & $exe @rest -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "가상환경(.venv) 생성 실패" }
} else {
    Write-Host "  기존 .venv 사용"
}
& $venvPy -m pip install --upgrade pip -q
& $venvPy -m pip install -r requirements.txt -q
if ($LASTEXITCODE -ne 0) { throw "pip 설치 실패 (인터넷 연결 확인)" }

# 2. FFmpeg ------------------------------------------------------------
Step "2/5 FFmpeg"
$ffOk = { param($p) Test-Exe $p @("-hide_banner", "-version") "ffmpeg version" }
if (& $ffOk "tools\ffmpeg.exe") {
    Write-Host "  이미 있음"
} else {
    $cands = @()
    $cands += Get-ChildItem "$OldRuntime\FFmpeg" -Recurse -Depth 4 -Filter ffmpeg.exe -ErrorAction SilentlyContinue |
              ForEach-Object { $_.FullName }
    $cands += (Get-Command ffmpeg.exe -ErrorAction SilentlyContinue).Source
    $reused = $false
    foreach ($c in ($cands | Where-Object { $_ })) {
        if (-not (& $ffOk $c)) { Write-Host "  건너뜀(실행 안 됨): $c"; continue }
        New-Item -ItemType Directory -Force tools | Out-Null
        Copy-Item "$(Split-Path $c)\*" tools\ -Include *.exe, *.dll -Force
        if (& $ffOk "tools\ffmpeg.exe") {
            Write-Host "  이미 PC에 있는 FFmpeg를 복사해서 사용: $c" -ForegroundColor Green
            $reused = $true; break
        }
        Remove-Item -Recurse -Force tools
    }
    if (-not $reused) {
        $zip = "$env:TEMP\ffmpeg-essentials.zip"
        Download "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" $zip
        $tmp = "$env:TEMP\autosub-ffmpeg-x"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
        Expand-Archive $zip $tmp
        New-Item -ItemType Directory -Force tools | Out-Null
        Copy-Item (Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1).FullName tools\ffmpeg.exe -Force
        Remove-Item -Recurse -Force $tmp, $zip
        if (-not (& $ffOk "tools\ffmpeg.exe")) { throw "FFmpeg 설치 실패" }
    }
}

# 3. whisper.cpp -------------------------------------------------------
Step "3/5 whisper.cpp 엔진"
$dst = "engines\whisper"
# -ojf(상세 JSON 출력)를 지원하는 버전이어야 함
$whOk = { param($p) Test-Exe $p @("-h") "output-json-full" }

function Install-WhisperFrom($folder) {
    if (Test-Path $dst) { Remove-Item -Recurse -Force $dst }
    New-Item -ItemType Directory -Force $dst | Out-Null
    Copy-Item "$folder\*" $dst -Include *.exe, *.dll -Force
    return (& $whOk "$dst\whisper-cli.exe")
}

function Install-WhisperZip($zip) {
    $tmp = "$env:TEMP\autosub-whisper-x"; Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
    Expand-Archive $zip $tmp
    $cli = Get-ChildItem $tmp -Recurse -Filter whisper-cli.exe | Select-Object -First 1
    if (-not $cli) { throw "zip 안에 whisper-cli.exe가 없습니다: $zip" }
    $ok = Install-WhisperFrom $cli.DirectoryName
    Remove-Item -Recurse -Force $tmp
    return $ok
}

$vkZip = Get-ChildItem $Root -Filter "whisper-vulkan-x64*.zip" | Select-Object -First 1
$done = $false
if ($vkZip) {
    # 1순위: GitHub Actions에서 받은 Vulkan 빌드 (항상 최신으로 교체)
    $done = Install-WhisperZip $vkZip.FullName
    if ($done) { Write-Host "  Vulkan(GPU) 빌드 설치: $($vkZip.Name)" -ForegroundColor Green }
    else { Write-Host "  $($vkZip.Name) 이 실행되지 않습니다. 다른 방법을 시도합니다." -ForegroundColor Yellow }
}
if (-not $done -and (& $whOk "$dst\whisper-cli.exe")) {
    Write-Host "  이미 있음"; $done = $true
}
if (-not $done) {
    # 2순위: 기존 자막생성툴 안내대로 PC에서 직접 빌드한 Vulkan whisper-cli
    $oldCands = @(
        "$OldRuntime\WhisperCppSource\build-vulkan\bin\Release\whisper-cli.exe",
        "$OldRuntime\WhisperCppSource\build-vulkan\bin\whisper-cli.exe",
        "C:\whisper.cpp\build-vulkan\bin\Release\whisper-cli.exe",
        "C:\whisper.cpp\build-vulkan\bin\whisper-cli.exe"
    )
    foreach ($c in $oldCands) {
        if (-not (Test-Path $c)) { continue }
        if (-not (& $whOk $c)) { Write-Host "  건너뜀(실행 안 되거나 오래된 버전): $c"; continue }
        if (Install-WhisperFrom (Split-Path $c)) {
            Write-Host "  이미 PC에 빌드된 Vulkan whisper-cli를 복사해서 사용: $c" -ForegroundColor Green
            $done = $true; break
        }
    }
}
if (-not $done) {
    # 3순위: 공식 CPU 빌드
    Write-Host "  GPU용 빌드가 없어 공식 CPU 빌드를 받습니다." -ForegroundColor Yellow
    Write-Host "  (GPU 가속을 쓰려면 README의 설치 2번 'Vulkan 빌드'를 참고하세요)"
    $zip = "$env:TEMP\whisper-bin-x64.zip"
    Remove-Item -Force $zip -ErrorAction SilentlyContinue
    Download "https://github.com/ggml-org/whisper.cpp/releases/latest/download/whisper-bin-x64.zip" $zip
    $done = Install-WhisperZip $zip
    Remove-Item -Force $zip -ErrorAction SilentlyContinue
    if (-not $done) { throw "whisper-cli 실행 실패 (Microsoft Visual C++ 재배포 패키지 설치가 필요할 수 있습니다)" }
}

# 4. 모델 --------------------------------------------------------------
Step "4/5 Whisper 모델 (large-v3-turbo Q8_0, 약 0.9GB)"
Download "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo-q8_0.bin" "models\ggml-large-v3-turbo-q8_0.bin"
Write-Host "  (기존에 받아둔 ggml 모델이 있으면 프로그램의 모델 목록에 자동으로 함께 표시됩니다)"

Step "5/5 Parakeet 모델 (교차검증용, 약 0.65GB)"
$pk = "models\parakeet-tdt-0.6b-v2-int8"
$hf = "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main"
foreach ($f in @("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")) {
    Download "$hf/$f" "$pk\$f"
}

# 점검 -----------------------------------------------------------------
Step "점검"
& $venvPy -c "import sherpa_onnx, numpy, tkinter; print('  Python 패키지 OK')"
if (& $ffOk "tools\ffmpeg.exe") { Write-Host "  FFmpeg OK" }
if (& $whOk "$dst\whisper-cli.exe") {
    $gpu = Test-Path "$dst\ggml-vulkan.dll"
    Write-Host ("  whisper-cli OK (" + $(if ($gpu) { "Vulkan GPU 지원" } else { "CPU 전용" }) + ")")
}

Write-Host ""
Write-Host "설치 완료! '자막만들기.bat'을 실행하세요." -ForegroundColor Green
