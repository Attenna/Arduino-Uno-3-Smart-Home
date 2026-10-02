# deploy_voice.ps1 — 语音交互模式一键部署（Qwen2.5 国内合规引擎）
# 用法：右键「使用 PowerShell 运行」，或在终端执行：
#   powershell -ExecutionPolicy Bypass -File deploy_voice.ps1
#
# 流程：检查 Python → 装依赖(国内镜像) → 下载 Qwen 模型(ModelScope) → 下载 Sherpa-ONNX 语音模型 → 自检
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$QWEN_DIR   = Join-Path $PSScriptRoot "models\qwen"
$PIP_MIRROR = "https://mirrors.aliyun.com/pypi/simple/"

function Step($msg) { Write-Host "`n==== $msg ====" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "  [!!] $msg" -ForegroundColor Yellow }

# ── 1. 检查 Python 3.13 ─────────────────────────────────────
Step "1/5 检查 Python 3.13"
try {
    $ver = py -3.13 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Ok "Python $ver"
} catch {
    Write-Host "未找到 Python 3.13。请安装：https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

# ── 2. 安装 Python 依赖（阿里云 PyPI 国内镜像）───────────────
Step "2/5 安装 Python 依赖（国内镜像 $PIP_MIRROR）"
py -3.13 -m pip install -r requirements.txt -i $PIP_MIRROR
if ($LASTEXITCODE -ne 0) { Write-Host "pip 安装失败" -ForegroundColor Red; exit 1 }
# llama-cpp-python 的源码构建依赖（Py3.13 常无预编译轮子；GPU 版在第 3.5 步处理）
py -3.13 -m pip install "scikit-build-core[pyproject]" cmake ninja pybind11 -i $PIP_MIRROR --quiet
Ok "构建依赖就绪"

# ── 3. 下载 Qwen2.5 模型（ModelScope 国内渠道）───────────────
Step "3/5 下载 Qwen2.5 模型（ModelScope 魔搭社区，国内渠道）"
$gguf = Get-ChildItem $QWEN_DIR -Filter "*q4_k_m*.gguf" -ErrorAction SilentlyContinue |
        Select-Object -First 1
if ($gguf) {
    Ok "模型已存在：$($gguf.Name)"
} else {
    py -3.13 download_qwen.py
    if ($LASTEXITCODE -ne 0) { Write-Host "Qwen 模型下载失败" -ForegroundColor Red; exit 1 }
}

# ── 3.5 安装/验证 CPU 推理引擎（目标机香橙派 AI Pro 为昇腾 NPU，不走 CUDA）──
Step "3.5 安装推理引擎 llama-cpp-python（CPU 版；香橙派同栈）"

function Test-LlamaSmoke() {
    # 真实加载模型 + 生成 1 token 验证（能抓出预编译 wheel 指令集不兼容等问题）
    $out = py -3.13 qwen_server.py --smoke 2>&1 | Out-String
    if ($LASTEXITCODE -eq 0 -and $out -match "SMOKE_OK") {
        Write-Host ($out.Split("`n") | Where-Object { $_ -match "SMOKE_OK" }) -ForegroundColor Green
        return $true
    }
    return $false
}

$engineOk = $false
# 路线 a：PyPI 预编译 CPU wheel（有则秒装）
py -3.13 -m pip install llama-cpp-python --upgrade --force-reinstall --no-deps -i $PIP_MIRROR 2>$null
if (Test-LlamaSmoke) {
    Ok "CPU 推理就绪（预编译 wheel）"
    $engineOk = $true
} else {
    # 路线 b：源码编译 CPU 版（本机指令集原生优化；需 VS2022 C++，约 3~10 分钟）
    Warn "预编译 wheel 不可用（无对应 Python 版本或指令集不兼容），转源码编译 CPU 版"
    $env:CMAKE_ARGS = "-DGGML_CUDA=off"
    py -3.13 -m pip install llama-cpp-python --force-reinstall --no-cache-dir `
        --no-build-isolation -i $PIP_MIRROR
    if (Test-LlamaSmoke) {
        Ok "CPU 推理就绪（源码编译）"
        $engineOk = $true
    }
}

if (-not $engineOk) {
    Warn "本地推理引擎未就绪。可改用云端模式（默认硅基流动）："
    Warn "  把 Key 粘贴到 llm_key.txt（llm.mode 无需改，启动器会自动切换）"
}

# ── 4. 下载 Sherpa-ONNX 语音模型（KWS + ASR + TTS，国内镜像）──
Step "4/5 下载 Sherpa-ONNX 语音模型（KWS 唤醒 + 流式 ASR + 本地 TTS）"
py -3.13 download_sherpa_models.py
if ($LASTEXITCODE -ne 0) { Write-Host "Sherpa 模型下载失败" -ForegroundColor Red; exit 1 }

# ── 5. 运行自检 ─────────────────────────────────────────────
Step "5/5 运行自检"
py -3.13 voice_assistant.py --self-check
$checkExit = $LASTEXITCODE

Write-Host ""
if ($checkExit -eq 0) {
    Write-Host "部署完成！启动语音助手：" -ForegroundColor Green
    Write-Host "    双击 start_voice.bat（自动拉起 Web 硬件网关，本地模式还会拉起 Qwen）" -ForegroundColor Green
    Write-Host "    或完整栈： py -3.13 start_all.py    （Web:5000 + 语音:8101 + 摄像头:8080）" -ForegroundColor Green
} else {
    Write-Host "自检有失败项，请按上方提示修复后重试。" -ForegroundColor Yellow
    Write-Host "提示：设备控制需要 Web 网关在线（自检里『硬件网关』项失败=run_web 未起或未插 A/B 板）。" -ForegroundColor Yellow
}
exit $checkExit
