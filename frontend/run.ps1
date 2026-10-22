param([ValidateSet('install', 'dev', 'build', 'type-check', 'test:unit')][string]$Command = 'dev')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npmCommand) {
        if ($Command -eq 'install') { & $npmCommand.Source ci } else { & $npmCommand.Source run $Command }
    } else {
        # Codex 的便携 Node 环境可能没有 npm；复用其现有 pnpm，不修改系统 PATH。
        $nodeCommand = Get-Command node -ErrorAction Stop
        $runtimeRoot = Split-Path (Split-Path $nodeCommand.Source -Parent) -Parent
        $pnpmCli = Join-Path $runtimeRoot 'node_modules\pnpm\bin\pnpm.cjs'
        if (!(Test-Path -LiteralPath $pnpmCli)) { throw '未找到 npm。请安装包含 npm 的 Node.js 24 LTS，再重新打开终端。' }
        $env:npm_config_cache = Join-Path (Split-Path $PSScriptRoot -Parent) 'data\outputs\npm-cache'
        $env:PNPM_HOME = Join-Path (Split-Path $PSScriptRoot -Parent) 'data\outputs\pnpm-home'
        if ($Command -eq 'install') { & $nodeCommand.Source $pnpmCli dlx npm ci } else { & $nodeCommand.Source $pnpmCli dlx npm run $Command }
    }
    if ($LASTEXITCODE -ne 0) { throw "前端命令失败：$Command（退出码 $LASTEXITCODE）" }
} finally { Pop-Location }
