# start_voice.ps1 — 语音助手 全自愈一键启动（开箱即用）
# 用法：双击 start_voice.bat 即可。脚本自动完成：
#   1) 清理上次残留进程（防止串口/8000端口被旧实例占用）
#   2) 缺依赖 → 自动装（阿里云镜像）；缺 Sherpa-ONNX 语音模型 → 自动下载
#   3) 缺 Qwen 权重 → 自动从 ModelScope 下载；qwen_server 未跑 → 自动拉起
#   4) 启动 voice_assistant.py
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot

$PIP_MIRROR  = "https://mirrors.aliyun.com/pypi/simple/"

function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Step($msg) { Write-Host "`n==== $msg ====" -ForegroundColor Cyan }

# 目标机香橙派 AI Pro 为昇腾 NPU（llama.cpp 不支持），推理走纯 CPU，无需 CUDA 运行时。

# ── 1. 清理残留进程（防端口占用）──────────────────────────────
Step "1/5 清理残留进程"
$stale = Get-CimInstance Win32_Process -Filter "Name like 'py%.exe'" -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -match "voice_assistant|qwen_server|download_qwen" }
if ($stale) {
    foreach ($p in $stale) {
        Write-Host "  结束旧实例 pid=$($p.ProcessId)" -ForegroundColor Yellow
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep 1
    Ok "旧实例已清理"
} else {
    Ok "无残留进程"
}

# ── 2. 依赖自愈 ─────────────────────────────────────────────
Step "2/5 检查 Python 依赖"
py -3.13 -c "import yaml, serial, httpx, mcp, sherpa_onnx, sounddevice, numpy" 2>$null
if ($LASTEXITCODE -ne 0) {
    Warn "依赖缺失，自动安装中（阿里云镜像）..."
    py -3.13 -m pip install --quiet pyserial pyyaml httpx mcp sherpa-onnx sounddevice numpy -i $PIP_MIRROR
    if ($LASTEXITCODE -ne 0) { Write-Host "依赖安装失败，请手动执行 deploy_voice.ps1" -ForegroundColor Red; exit 1 }
}
Ok "依赖齐全"

# ── 3. 模型自愈（Sherpa-ONNX + Qwen）─────────────────────────
Step "3/5 检查模型文件"
$sherpaRoot = Join-Path $PSScriptRoot "models\sherpa"
$sherpaOk = (Test-Path (Join-Path $sherpaRoot "kws\encoder.onnx")) -and
            (Test-Path (Join-Path $sherpaRoot "kws\keywords.txt")) -and
            (Test-Path (Join-Path $sherpaRoot "asr\encoder.onnx")) -and
            (Test-Path (Join-Path $sherpaRoot "tts\model.onnx"))
if (-not $sherpaOk) {
    Warn "Sherpa-ONNX 语音模型缺失，自动下载中（KWS+ASR+TTS，国内镜像）..."
    py -3.13 download_sherpa_models.py
    if ($LASTEXITCODE -ne 0) { Write-Host "Sherpa 模型下载失败" -ForegroundColor Red; exit 1 }
}
Ok "Sherpa-ONNX 模型就绪（KWS 唤醒 + 流式 ASR + 本地 TTS）"

$mode = py -3.13 -c "import yaml;print(yaml.safe_load(open('voice_config.yaml',encoding='utf-8'))['llm']['mode'])"
$useDashscope = $false

function Get-DashscopeKey {
    # 优先级：环境变量 > dashscope_key.txt > config api_key
    if ($env:DASHSCOPE_API_KEY) { return $env:DASHSCOPE_API_KEY }
    $keyFile = Join-Path $PSScriptRoot "dashscope_key.txt"
    if (Test-Path $keyFile) {
        $k = Get-Content $keyFile -ErrorAction SilentlyContinue |
             Where-Object { $_ -and -not $_.StartsWith("#") } |
             Select-Object -First 1
        if ($k) { return $k.Trim() }
    }
    $cfgKey = py -3.13 -c "import yaml;k=yaml.safe_load(open('voice_config.yaml',encoding='utf-8'))['llm'].get('api_key');print(k if k and k!='none' else '')"
    if ($cfgKey) { return $cfgKey }
    return ""
}

if ($mode -eq "dashscope") {
    Ok "LLM 引擎：阿里云百炼模式（无需本地模型）"
    $k = Get-DashscopeKey
    if ($k) { $env:DASHSCOPE_API_KEY = $k; Ok "百炼 Key 已就绪" }
    else {
        Warn "百炼模式但未找到 API Key！"
        Write-Host "      把 Key 粘贴保存到 PC_Test\dashscope_key.txt（或设环境变量 DASHSCOPE_API_KEY）" -ForegroundColor Yellow
        Write-Host "      申请地址：https://bailian.console.aliyun.com" -ForegroundColor Yellow
        Write-Host "      将继续启动，但语音对话会失败..." -ForegroundColor Yellow
    }
} else {
    $gguf = Get-ChildItem (Join-Path $PSScriptRoot "models\qwen") -Filter "*.gguf" -ErrorAction SilentlyContinue |
            Select-Object -First 1
    if (-not $gguf) {
        Warn "Qwen 权重缺失，自动从 ModelScope（国内渠道）下载（~2GB，视网速几分钟）..."
        py -3.13 -c "import modelscope" 2>$null
        if ($LASTEXITCODE -ne 0) {
            py -3.13 -m pip install --quiet modelscope -i $PIP_MIRROR
        }
        py -3.13 download_qwen.py
        if ($LASTEXITCODE -ne 0) { Write-Host "Qwen 模型下载失败" -ForegroundColor Red; exit 1 }
    } else { Ok "Qwen 权重就绪：$($gguf.Name)" }

    py -3.13 -c "import llama_cpp" 2>$null
    if ($LASTEXITCODE -ne 0) {
        # 本地推理引擎缺失：若已存百炼 Key，自动切换云端模式
        $k = Get-DashscopeKey
        if ($k) {
            $env:DASHSCOPE_API_KEY = $k
            $useDashscope = $true
            Warn "本地推理引擎缺失，已自动切换为阿里云百炼模式（Key 来自 dashscope_key.txt/环境变量/配置）"
        } else {
            Write-Host "llama-cpp-python 未安装（本地推理引擎缺失），无法启动！" -ForegroundColor Red
            Write-Host "  方案a：运行一键部署脚本自动安装（有 N 卡会自动装 CUDA GPU 版）：" -ForegroundColor Yellow
            Write-Host "        powershell -ExecutionPolicy Bypass -File deploy_voice.ps1" -ForegroundColor Yellow
            Write-Host "  方案b：改用阿里云百炼（免本地算力）：" -ForegroundColor Yellow
            Write-Host "        1) https://bailian.console.aliyun.com 开通并创建 API Key" -ForegroundColor Yellow
            Write-Host "        2) 把 Key 粘贴保存到 PC_Test\dashscope_key.txt，重新双击本脚本" -ForegroundColor Yellow
            exit 1
        }
    }
}

# ── 4. 拉起本地 Qwen 服务（仅本地模式）───────────────────────
if (-not $useDashscope) {
    Step "4/5 检查本地 Qwen 服务"
    $llmPort = 8000
    $llmUrl = "http://127.0.0.1:$llmPort/v1/models"
    $up = $false
    try { $null = Invoke-RestMethod $llmUrl -TimeoutSec 2; $up = $true; Ok "本地 Qwen 服务运行中" } catch {}
    if (-not $up) {
        Write-Host "  正在后台启动 qwen_server（模型加载 10~30 秒）..."
        Start-Process -WindowStyle Minimized py -ArgumentList "-3.13","qwen_server.py"
        $tries = 0
        while ($tries -lt 40) {
            Start-Sleep 1
            try { $null = Invoke-RestMethod $llmUrl -TimeoutSec 2; $up = $true; Ok "本地 Qwen 服务就绪"; break } catch {}
            $tries++
        }
        if (-not $up) {
            Write-Host "Qwen 服务启动超时" -ForegroundColor Red
            exit 1
        }
    }
} else {
    Write-Host "`n==== 4/5 跳过本地服务（百炼云端推理）====" -ForegroundColor Cyan
}

# ── 5. 启动语音助手 ─────────────────────────────────────────
Step "5/5 启动语音助手"
Write-Host "🎤 说「Hey Bota」唤醒我（也可直接打字发指令；Ctrl+C 退出）`n" -ForegroundColor Cyan
if ($useDashscope) {
    py -3.13 voice_assistant.py --llm-mode dashscope
} else {
    py -3.13 voice_assistant.py
}
Write-Host "`n语音助手已退出。"
