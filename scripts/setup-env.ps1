# PowerShell script to set up environment variables for local development
# Run this script before starting the services

Write-Host "Setting up Callcenter environment variables..." -ForegroundColor Green

# Load .env file if it exists
$envFile = "config\.env"
if (Test-Path $envFile) {
    Write-Host "Loading environment variables from $envFile" -ForegroundColor Yellow
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
            Write-Host "  Set $key" -ForegroundColor Gray
        }
    }
} else {
    Write-Host "Warning: $envFile not found. Please create it from config\.env.example" -ForegroundColor Red
}

# Set Google Application Credentials if service account file exists
$serviceAccountPath = "config\gcp-service-account.json"
if (Test-Path $serviceAccountPath) {
    $fullPath = (Resolve-Path $serviceAccountPath).Path
    [Environment]::SetEnvironmentVariable("GOOGLE_APPLICATION_CREDENTIALS", $fullPath, "Process")
    Write-Host "Set GOOGLE_APPLICATION_CREDENTIALS to $fullPath" -ForegroundColor Green
} else {
    Write-Host "Warning: Service account file not found at $serviceAccountPath" -ForegroundColor Yellow
    Write-Host "You can use 'gcloud auth application-default login' instead" -ForegroundColor Yellow
}

Write-Host "`nEnvironment setup complete!" -ForegroundColor Green
Write-Host "You can now run:" -ForegroundColor Cyan
Write-Host "  Backend: cd api\src && python server.py" -ForegroundColor Cyan
Write-Host "  Agent:   cd agents\src && python -m agents.src.gemini_agent" -ForegroundColor Cyan
Write-Host "  Frontend: cd frontend && npm run dev" -ForegroundColor Cyan



