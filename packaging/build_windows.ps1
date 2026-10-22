param([string]$Python = '', [string]$OutputRoot = '', [switch]$Console, [switch]$SkipArchive)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
if (!$Python) { $Python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (!$OutputRoot) { $OutputRoot = Join-Path $projectRoot ('release\' + (Get-Date -Format 'yyyyMMdd-HHmmss')) }
$OutputRoot = [System.IO.Path]::GetFullPath($OutputRoot)
if (Test-Path -LiteralPath $OutputRoot) { throw "输出目录已存在；为保留旧版本，请使用新的目录：$OutputRoot" }
if (!(Test-Path -LiteralPath $Python)) { throw "Python 不存在：$Python" }
New-Item -ItemType Directory -Path $OutputRoot | Out-Null
$stage = Join-Path $OutputRoot 'build-resources'
$work = Join-Path $OutputRoot 'build-work'
$dist = Join-Path $OutputRoot 'dist'
$buildLog = Join-Path $OutputRoot 'build.log'
Push-Location $projectRoot
try {
    & $Python -X utf8 -c "import torch,cv2,ultralytics,fastapi,uvicorn,PyInstaller,tkinter; assert torch.version.cuda, '必须使用现有 CUDA 版 PyTorch'; print('torch',torch.__version__,'cuda',torch.version.cuda,'available',torch.cuda.is_available()); print('PyInstaller',PyInstaller.__version__)"
    if ($LASTEXITCODE -ne 0) { throw '构建依赖检查失败；只安装 packaging/requirements-build.txt，不要替换 CUDA torch' }
    & (Join-Path $projectRoot 'frontend\run.ps1') build
    if (!(Test-Path -LiteralPath 'frontend\dist\index.html')) { throw 'Vue 构建产物缺失' }
    if (!(Test-Path -LiteralPath 'models\yolo26n.pt')) { throw '需要已下载的 models/yolo26n.pt，不能生成联网依赖包' }
    $ffprobeCommand = Get-Command ffprobe.exe -ErrorAction Stop
    & $Python -X utf8 (Join-Path $PSScriptRoot 'prepare_release.py') --stage $stage --ffprobe $ffprobeCommand.Source
    if ($LASTEXITCODE -ne 0) { throw '资源/许可证准备失败' }
    $env:SMARTVISION_BUILD_STAGE = $stage
    $env:SMARTVISION_CONSOLE_BUILD = $(if ($Console) {'1'} else {'0'})
    & $Python -X utf8 -X faulthandler -m PyInstaller --noconfirm --distpath $dist --workpath $work (Join-Path $PSScriptRoot 'smartvision.spec') *> $buildLog
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "PyInstaller 退出码 $LASTEXITCODE；保留日志后重试一次。"
        & $Python -X utf8 -X faulthandler -m PyInstaller --noconfirm --distpath $dist --workpath $work (Join-Path $PSScriptRoot 'smartvision.spec') *> ($buildLog + '.retry.log')
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败（$LASTEXITCODE），请查看 $buildLog 及重试日志" }
    }
    $application = Join-Path $dist 'SmartVision'
    & $Python -X utf8 (Join-Path $PSScriptRoot 'verify_sources.py') --exe (Join-Path $application 'SmartVision.exe') --report (Join-Path $OutputRoot 'source-match.json')
    if ($LASTEXITCODE -ne 0) { throw '内嵌代码校验失败；请保留日志并使用全新输出目录重建' }
    foreach ($file in @('SmartVision.exe','_internal\python311.dll','_internal\models\yolo26n.pt','_internal\bin\ffprobe.exe','_internal\frontend\dist\index.html','_internal\backend\database\schema.sql','_internal\backend\database\migration_v3.sql')) {
        if (!(Test-Path -LiteralPath (Join-Path $application $file))) { throw "关键文件缺失：$file" }
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'USER_GUIDE.md') -Destination (Join-Path $application '使用说明.md')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'README_PACKAGING.md') -Destination (Join-Path $application '构建说明.md')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'DISTRIBUTION_LICENSE.md') -Destination (Join-Path $application '源码与许可.md')
    # Python zipfile uses ZIP64; Compress-Archive cannot safely package >2GB DLLs.
    if (!$SkipArchive) {
        & $Python -X utf8 (Join-Path $PSScriptRoot 'finish_release.py') --folder $application --zip (Join-Path $OutputRoot 'SmartVision-win64.zip')
        if ($LASTEXITCODE -ne 0) { throw 'ZIP64 归档或核验失败' }
        Write-Output "分发 ZIP：$(Join-Path $OutputRoot 'SmartVision-win64.zip')"
    } else { Write-Warning '已跳过归档；实际 EXE 验收并补齐报告后，请调用 finish_release.py 生成最终 ZIP。' }
    Write-Output "应用目录：$application"
    Write-Output "构建日志：$buildLog"
    Write-Warning '生成产物后仍需实际运行 EXE 验证 CUDA、CPU、持久化和退出；生成 EXE 不等于验收成功。'
} finally { Pop-Location }
