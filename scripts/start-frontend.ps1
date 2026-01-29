# Start the frontend development server
Write-Host "Starting Callcenter Frontend..." -ForegroundColor Green

# Change to frontend directory
Set-Location "$PSScriptRoot\..\frontend"

# Check if node_modules exists
if (-not (Test-Path "node_modules")) {
    Write-Host "Installing dependencies..." -ForegroundColor Yellow
    npm install
}

# Start the dev server
Write-Host "Starting Vite dev server on port 3000..." -ForegroundColor Cyan
npm run dev



