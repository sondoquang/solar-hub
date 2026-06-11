# Mo cloudflared tunnel cho Hub backend va tu dong noi day vao he thong:
#   1. Chay cloudflared quick tunnel -> localhost:8000, lay URL trycloudflare.com moi.
#   2. Ghi MEDIA_PUBLIC_BASE_URL vao backend/.env (thay dong cu neu co).
#   3. Restart backend + celery de nap env moi.
#   4. Sua cac URL /media/ da luu trong DB sang host moi (manage.py set_media_public_url).
#
# Dung khi dev can sync san pham CO ANH xuong cac site that (anh phai tai duoc
# tu internet). URL trycloudflare doi moi lan chay lai -> chay lai script nay.
# Dung tunnel: Ctrl+C (script giu tunnel o foreground).
#
# Cach chay (tu thu muc goc repo):
#   powershell -ExecutionPolicy Bypass -File scripts\dev-tunnel.ps1

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot "backend\.env"

# --- Tim cloudflared ----------------------------------------------------
$cloudflared = $null
try { $cloudflared = (Get-Command cloudflared -ErrorAction Stop).Source } catch {}
if (-not $cloudflared) {
    $candidates = @(
        "$env:ProgramFiles\cloudflared\cloudflared.exe",
        "${env:ProgramFiles(x86)}\cloudflared\cloudflared.exe"
    )
    $cloudflared = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $cloudflared) {
    Write-Error "Khong tim thay cloudflared. Cai bang: winget install --id Cloudflare.cloudflared -e"
}

# --- Chay tunnel va cho URL ----------------------------------------------
$log = Join-Path $env:TEMP "cloudflared-solarhub.log"
if (Test-Path $log) { Remove-Item $log -Force -Confirm:$false }

$proc = Start-Process -FilePath $cloudflared `
    -ArgumentList "tunnel", "--url", "http://localhost:8000", "--logfile", $log `
    -PassThru -WindowStyle Hidden

$url = $null
foreach ($i in 1..60) {
    Start-Sleep -Seconds 1
    if (Test-Path $log) {
        $hit = Select-String -Path $log -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" |
            Select-Object -First 1
        if ($hit) { $url = $hit.Matches[0].Value; break }
    }
}
if (-not $url) {
    Stop-Process -Id $proc.Id -Force -Confirm:$false
    Write-Error "Khong lay duoc URL tunnel sau 60s (xem log: $log)"
}
Write-Host "Tunnel: $url" -ForegroundColor Green

# --- Ghi MEDIA_PUBLIC_BASE_URL vao backend/.env ---------------------------
$lines = Get-Content $envFile | Where-Object { $_ -notmatch "^MEDIA_PUBLIC_BASE_URL=" }
$lines += "MEDIA_PUBLIC_BASE_URL=$url"
$lines | Set-Content $envFile -Encoding ascii
Write-Host "Da ghi MEDIA_PUBLIC_BASE_URL vao backend\.env"

# --- Restart cac service doc settings -------------------------------------
Push-Location $repoRoot
try {
    docker compose restart backend celery_worker_interactive celery_worker_periodic celery_beat
    # Sua URL /media/ cu da luu trong DB sang host moi
    docker compose exec backend python manage.py set_media_public_url $url
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "San sang dong bo san pham co anh. Tunnel dang chay (PID $($proc.Id))." -ForegroundColor Green
Write-Host "Giu cua so nay mo trong luc sync; nhan Ctrl+C de dung tunnel."

# Giu script song theo tunnel; Ctrl+C / dong cua so se dung ca hai.
try {
    Wait-Process -Id $proc.Id
} finally {
    if (-not $proc.HasExited) { Stop-Process -Id $proc.Id -Force -Confirm:$false }
}
