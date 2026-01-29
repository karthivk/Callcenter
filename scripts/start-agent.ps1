# Start the LiveKit agent
Write-Host "Starting Callcenter LiveKit Agent..." -ForegroundColor Green

# Load environment variables
& "$PSScriptRoot\setup-env.ps1"

# Change to agents directory
Set-Location "$PSScriptRoot\..\agents\src"

# Start the agent
Write-Host "Connecting agent to LiveKit Cloud..." -ForegroundColor Cyan
python -m agents.src.gemini_agent



