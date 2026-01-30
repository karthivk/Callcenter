# Local Setup Guide - Callcenter

This guide walks you through setting up MSG91, LiveKit Cloud, Google Cloud (Vertex AI), and running the application locally.

---

## Prerequisites

- Python 3.12+ installed
- Node.js 18+ and npm installed
- Google Cloud account with billing enabled
- MSG91 account
- LiveKit Cloud account (free tier available)

---

## Step 0: ngrok Setup (For Local Development with Twilio Webhooks)

### Why ngrok?
Twilio needs to send webhooks to your local server, but `localhost` isn't accessible from the internet. ngrok creates a secure tunnel to expose your local server.

### 0.1 Install ngrok

1. **Download ngrok:**
   - Go to https://ngrok.com/download
   - Download for Windows
   - Extract `ngrok.exe` to a folder in your PATH (e.g., `C:\Program Files\ngrok\`)

2. **Or use Chocolatey (if installed):**
   ```powershell
   choco install ngrok
   ```

### 0.2 Sign Up and Authenticate

1. **Create free account:**
   - Go to https://dashboard.ngrok.com/signup
   - Sign up (free tier is sufficient)

2. **Get your auth token:**
   - Go to https://dashboard.ngrok.com/get-started/your-authtoken
   - Copy your authtoken

3. **Authenticate ngrok:**
   ```powershell
   ngrok config add-authtoken YOUR_AUTH_TOKEN
   ```

### 0.3 Start ngrok Tunnel

1. **Start your Flask server first:**
   ```powershell
   cd C:\Users\karth\PycharmProjects\Callcenter\api\src
   python server.py
   ```
   Your server should be running on `http://localhost:8081`

2. **In a NEW terminal, start ngrok:**
   ```powershell
   ngrok http 8081
   ```

3. **Copy the HTTPS URL:**
   You'll see output like:
   ```
   Forwarding  https://abc123-def456.ngrok-free.app -> http://localhost:8081
   ```
   Copy the HTTPS URL (the one starting with `https://`)

4. **Update your `.env` file:**
   ```bash
   API_BASE_URL=https://abc123-def456.ngrok-free.app
   ```
   ⚠️ **Important:** Use the HTTPS URL, not HTTP!

5. **Restart your Flask server** to pick up the new `API_BASE_URL`

### 0.4 Keep ngrok Running

- Keep the ngrok terminal window open while testing
- The URL changes each time you restart ngrok (unless you have a paid plan)
- Update `API_BASE_URL` in `.env` if you restart ngrok

### Alternative: Static ngrok URL (Paid Plan)
- Free ngrok URLs change on restart
- Paid plans ($8/month) allow static domains like `https://yourname.ngrok.io`
- Useful for production-like testing

---

## Step 1: Google Cloud Setup (Vertex AI for Gemini)

### 1.1 Create/Select GCP Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Note your **Project ID** (e.g., `my-callcenter-project`)

### 1.2 Enable Required APIs

```bash
# Install Google Cloud CLI if not already installed
# https://cloud.google.com/sdk/docs/install

# Authenticate
gcloud auth login

# Set your project
gcloud config set project YOUR_PROJECT_ID

# Enable Vertex AI API
gcloud services enable aiplatform.googleapis.com

# Enable Gemini API
gcloud services enable generativelanguage.googleapis.com
```

### 1.3 Set Up Application Default Credentials (ADC)

**No service account key file needed!** The code uses Application Default Credentials (ADC), which automatically uses:
- Your `gcloud auth` credentials (for local development)
- The Cloud Run service account (when deployed)
- VM service account (when running on GCE)

#### For Local Development:

1. **Install Google Cloud SDK** (if not already installed):
   - Download from: https://cloud.google.com/sdk/docs/install

2. **Authenticate with your Google account:**
   ```powershell
   gcloud auth login
   gcloud auth application-default login
   ```

3. **Set your project:**
   ```powershell
   gcloud config set project delta-clarity-483003-f1
   ```

4. **Grant your user account Vertex AI permissions:**
   - Go to: https://console.cloud.google.com/iam-admin/iam?project=delta-clarity-483003-f1
   - Find your user account (the email you used for `gcloud auth login`)
   - Click the edit icon (pencil)
   - Add role: `Vertex AI User` (roles/aiplatform.user)
   - Click "Save"

**That's it!** No service account key file needed. The code will automatically use your authenticated credentials.

#### For Cloud Run Deployment:

- Cloud Run will use the default Compute Engine service account
- Make sure that service account has `Vertex AI User` role
- No code changes needed - ADC works automatically

---

## Step 2: LiveKit Cloud Setup

### 2.1 Create LiveKit Cloud Account

1. Go to [LiveKit Cloud](https://cloud.livekit.io/)
2. Sign up for a free account
3. Create a new project

### 2.2 Get LiveKit Credentials

1. In your LiveKit Cloud dashboard, go to **Settings** > **API Keys**
2. Create a new API key or use the default one
3. Copy:
   - **URL** (e.g., `https://your-project.livekit.cloud`)
   - **API Key**
   - **API Secret**

**Important URLs:**
- **HTTP URL** (for API): `https://your-project.livekit.cloud`
- **WebSocket URL** (for agents): `wss://your-project.livekit.cloud` (change `https://` to `wss://`)

### 2.3 Configure Agent in LiveKit Cloud

1. Go to **Agents** in LiveKit Cloud dashboard
2. Note the agent name (default: `callcenter-agent` or create a new one)
3. The agent will connect automatically when deployed

**For Local Development:**
- You'll need to run the agent locally and connect it to LiveKit Cloud
- The agent connects via WebSocket to LiveKit Cloud

---

## Step 3: MSG91 Setup

### 3.1 Create MSG91 Account

1. Go to [MSG91](https://msg91.com/)
2. Sign up for an account
3. Complete verification (may require business verification for voice calls)

### 3.2 Get MSG91 Credentials

1. Log in to MSG91 dashboard
2. Go to **API** section
3. Find your **Auth Key** (API Key)
4. Go to **Voice** section
5. Get your **Sender ID** (Caller ID)
6. Create a **Flow** for outbound calls:
   - Go to **Voice** > **Flow**
   - Create a new flow
   - Configure it to connect to LiveKit SIP endpoint
   - Note the **Flow ID**

### 3.3 Configure MSG91 Flow for LiveKit

Your MSG91 flow needs to:
1. Receive the outbound call request
2. Connect to LiveKit Cloud via SIP
3. Pass the room name and metadata

**MSG91 Flow Configuration:**
- **SIP Endpoint:** Your LiveKit Cloud SIP endpoint
- **Room Name:** Pass from flow data
- **Webhook URL:** Your API webhook endpoint (`/webhook/msg91`)

**Note:** MSG91 SIP integration with LiveKit may require:
- SIP trunk configuration in MSG91
- LiveKit Cloud SIP configuration
- Proper SIP credentials exchange

---

## Step 4: Local Environment Configuration

### 4.1 Create Environment File

```bash
# Copy the example file
cp config/.env.example config/.env
```

Or create `config/.env` manually with:

```bash
# MSG91 Configuration
MSG91_AUTH_KEY=your_msg91_auth_key_here
MSG91_SENDER_ID=your_caller_id_here
MSG91_FLOW_ID=your_flow_id_here

# LiveKit Cloud Configuration
# HTTP URL for API calls (backend)
LIVEKIT_HTTP_URL=https://your-project.livekit.cloud
# WebSocket URL for agent connections (agents)
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=your_livekit_api_key_here
LIVEKIT_API_SECRET=your_livekit_api_secret_here

# Google Cloud (Vertex AI)
GCP_PROJECT_ID=your_gcp_project_id
VERTEX_AI_LOCATION=us-central1

# API Configuration
API_BASE_URL=http://localhost:8081
PORT=8081

# Agent Configuration
LIVEKIT_AGENT_NAME=callcenter-agent
```

### 4.2 Set Environment Variables (Alternative)

For local development, you can also set environment variables directly:

**Windows PowerShell:**
```powershell
$env:MSG91_AUTH_KEY="your_key"
$env:LIVEKIT_HTTP_URL="https://your-project.livekit.cloud"
$env:LIVEKIT_API_KEY="your_key"
$env:LIVEKIT_API_SECRET="your_secret"
$env:GCP_PROJECT_ID="your_project_id"
$env:VERTEX_AI_LOCATION="us-central1"
# No GOOGLE_APPLICATION_CREDENTIALS needed - using Application Default Credentials (ADC)
# Just make sure you've run: gcloud auth application-default login
```

**Windows CMD:**
```cmd
set MSG91_AUTH_KEY=your_key
set LIVEKIT_HTTP_URL=https://your-project.livekit.cloud
set LIVEKIT_API_KEY=your_key
set LIVEKIT_API_SECRET=your_secret
set GCP_PROJECT_ID=your_project_id
set VERTEX_AI_LOCATION=us-central1
# No GOOGLE_APPLICATION_CREDENTIALS needed - using Application Default Credentials (ADC)
# Just make sure you've run: gcloud auth application-default login
```

---

## Step 5: Install Dependencies

### 5.1 Backend (Python)

```bash
# Create virtual environment (recommended)
cd api
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Windows CMD:
venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt
```

### 5.2 Frontend (Node.js)

```bash
cd frontend
npm install
```

---

## Step 6: Run the Application Locally

### 6.1 Start the Backend API

**Terminal 1:**
```bash
cd api/src
python server.py
```

The API will run on `http://localhost:8081`

**Verify it's working:**
```bash
curl http://localhost:8081/health
# Should return: ok
```

### 6.2 Start the LiveKit Agent

**Terminal 2:**
```bash
# Make sure environment variables are set
cd agents/src

# Load environment variables from config/.env
# The agent will automatically read from .env file via python-dotenv
python -m agents.src.gemini_agent
```

The agent will:
- Connect to LiveKit Cloud via WebSocket
- Wait for rooms to be created
- Handle incoming calls automatically

**Note:** The agent needs these environment variables (set in `config/.env` or as system env vars):
- `LIVEKIT_URL` - WebSocket URL (usually `wss://your-project.livekit.cloud`)
- `LIVEKIT_API_KEY` - API key from LiveKit Cloud
- `LIVEKIT_API_SECRET` - API secret from LiveKit Cloud
- `LIVEKIT_AGENT_NAME` - Agent name (must match in LiveKit Cloud dashboard)
- `GCP_PROJECT_ID` - Your Google Cloud project ID
- `VERTEX_AI_LOCATION` - Vertex AI region (e.g., `us-central1`)
- **No `GOOGLE_APPLICATION_CREDENTIALS` needed** - Uses Application Default Credentials (ADC)

**Important:** The `LIVEKIT_URL` for agents should be the WebSocket URL, not the HTTP URL:
- HTTP URL: `https://your-project.livekit.cloud` (for API calls)
- WebSocket URL: `wss://your-project.livekit.cloud` (for agent connections)

### 6.3 Start the Frontend

**Terminal 3:**
```bash
cd frontend
npm run dev
```

The frontend will run on `http://localhost:3000`

---

## Step 7: Test the Application

1. Open `http://localhost:3000` in your browser
2. Fill in the form:
   - **Phone Number:** Your test phone number (e.g., `+919876543210`)
   - **Language:** Select a language
   - **Agent Prompt:** Enter a prompt for the AI agent
3. Click **Initiate Call**
4. The system will:
   - Create a LiveKit room
   - Initiate MSG91 outbound call
   - Connect the call to LiveKit
   - Agent will handle the conversation

---

## Troubleshooting

### Backend Issues

**Port already in use:**
```bash
# Change PORT in config/.env or set environment variable
set PORT=8082
```

**Missing dependencies:**
```bash
pip install -r api/requirements.txt
```

**LiveKit connection errors:**
- Verify `LIVEKIT_HTTP_URL`, `LIVEKIT_API_KEY`, and `LIVEKIT_API_SECRET`
- Check LiveKit Cloud dashboard for connection status

### Agent Issues

**Agent not connecting:**
- Verify environment variables are set
- Check LiveKit Cloud agent configuration
- Ensure agent name matches in both API and agent code

**Gemini API errors:**
- Verify `GCP_PROJECT_ID` and `VERTEX_AI_LOCATION`
- Check service account has correct permissions
- Ensure Vertex AI API is enabled
- Verify you've run `gcloud auth application-default login` for local dev

**Import errors:**
```bash
# Make sure you're in the right directory and PYTHONPATH is set
cd agents
set PYTHONPATH=%CD%
python -m agents.src.gemini_agent
```

### Frontend Issues

**Cannot connect to API:**
- Verify backend is running on port 8081
- Check `VITE_API_URL` in frontend or use proxy in `vite.config.js`
- Check CORS settings in `api/src/server.py`

**Build errors:**
```bash
cd frontend
rm -rf node_modules
npm install
```

### MSG91 Issues

**Call not initiating:**
- Verify `MSG91_AUTH_KEY`, `MSG91_SENDER_ID`, and `MSG91_FLOW_ID`
- Check MSG91 dashboard for API usage and limits
- Verify phone number format (should be without + or with country code)

**Webhook not receiving events:**
- For local development, use a tool like [ngrok](https://ngrok.com/) to expose your local API:
  ```bash
  ngrok http 8081
  ```
- Update `API_BASE_URL` in `.env` to the ngrok URL
- Update webhook URL in MSG91 flow configuration

---

## Development Tips

### Using ngrok for Local Webhooks

1. Install ngrok: https://ngrok.com/download
2. Start your backend API
3. In another terminal:
   ```bash
   ngrok http 8081
   ```
4. Copy the HTTPS URL (e.g., `https://abc123.ngrok.io`)
5. Update `API_BASE_URL` in `.env` to the ngrok URL
6. Update MSG91 webhook URL to: `https://abc123.ngrok.io/webhook/msg91`

### Testing Without MSG91

You can test the LiveKit room creation and agent without MSG91:

1. Comment out MSG91 call initiation in `api/src/server.py`
2. Create a room manually via API
3. Connect to the room using LiveKit client SDK
4. Test the agent conversation

### Debugging

**Enable verbose logging:**
- Backend: Already configured in `server.py`
- Agent: Set `logging.basicConfig(level=logging.DEBUG)` in `gemini_agent.py`

**Check LiveKit Cloud dashboard:**
- View active rooms
- Monitor agent connections
- Check SIP connections

---

## Next Steps

1. **Test locally** with all components running
2. **Deploy to Cloud Run** (see `DEVELOPMENT_PLAN.md`)
3. **Set up production environment variables**
4. **Configure production webhooks**
5. **Monitor and optimize**

---

## Quick Reference

### Required Environment Variables

```bash
# MSG91
MSG91_AUTH_KEY
MSG91_SENDER_ID
MSG91_FLOW_ID

# LiveKit
LIVEKIT_HTTP_URL
LIVEKIT_API_KEY
LIVEKIT_API_SECRET
LIVEKIT_AGENT_NAME

# Google Cloud
GCP_PROJECT_ID
VERTEX_AI_LOCATION
# No GOOGLE_APPLICATION_CREDENTIALS needed - uses Application Default Credentials (ADC)

# API
API_BASE_URL
PORT
```

### Service URLs

- **Backend API:** http://localhost:8081
- **Frontend:** http://localhost:3000
- **LiveKit Cloud:** Your project URL from dashboard
- **MSG91 API:** https://control.msg91.com/api/v5/

---

## Support Resources

- [LiveKit Documentation](https://docs.livekit.io/)
- [MSG91 API Documentation](https://docs.msg91.com/)
- [Google Vertex AI Documentation](https://cloud.google.com/vertex-ai/docs)
- [Gemini API Documentation](https://ai.google.dev/docs)

