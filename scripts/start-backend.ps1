# Start the backend API server
Write-Host "Starting Callcenter Backend API..." -ForegroundColor Green

# Load environment variables
& "$PSScriptRoot\setup-env.ps1"

# Change to API directory
Set-Location "$PSScriptRoot\..\api\src"

# Start the server
Write-Host "Starting Flask server on port 8081..." -ForegroundColor Cyan
python server.py



