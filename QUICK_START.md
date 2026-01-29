# Quick Start Guide - Callcenter

This is a condensed guide to get you up and running quickly. For detailed setup, see `LOCAL_SETUP.md`.

## Prerequisites Checklist

- [ ] Python 3.12+ installed
- [ ] Node.js 18+ installed
- [ ] Google Cloud account with billing enabled
- [ ] LiveKit Cloud account (free tier available)
- [ ] MSG91 account

---

## Step 1: Get Your Credentials

### Google Cloud (5 minutes)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create/select a project
3. Enable APIs:
   ```bash
   gcloud services enable aiplatform.googleapis.com
   gcloud services enable generativelanguage.googleapis.com
   ```
4. Create service account with `Vertex AI User` role
5. Download JSON key → save as `config/gcp-service-account.json`

### LiveKit Cloud (2 minutes)

1. Sign up at [cloud.livekit.io](https://cloud.livekit.io/)
2. Create a project
3. Go to **Settings** > **API Keys**
4. Copy:
   - URL: `https://your-project.livekit.cloud`
   - API Key
   - API Secret

### MSG91 (10 minutes)

1. Sign up at [msg91.com](https://msg91.com/)
2. Complete verification
3. Get from dashboard:
   - Auth Key (API Key)
   - Sender ID (Caller ID)
4. Create a Flow for outbound calls
5. Note the Flow ID

---

## Step 2: Configure Environment

1. Create `config/.env` file:
   ```bash
   # Copy from example (if visible) or create manually
   ```

2. Fill in your credentials:
   ```bash
   # MSG91
   MSG91_AUTH_KEY=your_key_here
   MSG91_SENDER_ID=your_sender_id
   MSG91_FLOW_ID=your_flow_id

   # LiveKit
   LIVEKIT_HTTP_URL=https://your-project.livekit.cloud
   LIVEKIT_URL=wss://your-project.livekit.cloud
   LIVEKIT_API_KEY=your_api_key
   LIVEKIT_API_SECRET=your_api_secret
   LIVEKIT_AGENT_NAME=callcenter-agent

   # Google Cloud
   GCP_PROJECT_ID=your_project_id
   VERTEX_AI_LOCATION=us-central1

   # API
   API_BASE_URL=http://localhost:8081
   PORT=8081
   ```

3. Set Google credentials:
   ```powershell
   # Option 1: Service account file
   $env:GOOGLE_APPLICATION_CREDENTIALS="C:\Users\karth\Cursor_Version\Callcenter\config\gcp-service-account.json"

   # Option 2: gcloud auth
   gcloud auth application-default login
   ```

---

## Step 3: Install Dependencies

### Backend
```powershell
cd api
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Frontend
```powershell
cd frontend
npm install
```

---

## Step 4: Run the Application

### Option A: Using Helper Scripts (Recommended)

**Terminal 1 - Backend:**
```powershell
.\scripts\start-backend.ps1
```

**Terminal 2 - Agent:**
```powershell
.\scripts\start-agent.ps1
```

**Terminal 3 - Frontend:**
```powershell
.\scripts\start-frontend.ps1
```

### Option B: Manual Start

**Terminal 1 - Backend:**
```powershell
cd api\src
python server.py
```

**Terminal 2 - Agent:**
```powershell
cd agents\src
python -m agents.src.gemini_agent
```

**Terminal 3 - Frontend:**
```powershell
cd frontend
npm run dev
```

---

## Step 5: Test

1. Open `http://localhost:3000` in your browser
2. Fill in the form:
   - Phone number (e.g., `+919876543210`)
   - Language
   - Agent prompt
3. Click **Initiate Call**
4. Check the logs in all three terminals

---

## Troubleshooting

### Backend won't start
- Check port 8081 is not in use
- Verify `config/.env` exists and has correct values
- Check Python dependencies: `pip install -r api/requirements.txt`

### Agent won't connect
- Verify `LIVEKIT_URL` uses `wss://` (WebSocket), not `https://`
- Check `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` are correct
- Ensure `LIVEKIT_AGENT_NAME` matches in LiveKit Cloud dashboard
- Check Google Cloud credentials are set correctly

### Frontend can't connect to API
- Verify backend is running on port 8081
- Check browser console for CORS errors
- Verify `VITE_API_URL` in frontend or use proxy in `vite.config.js`

### MSG91 calls not working
- Verify all MSG91 credentials in `.env`
- Check MSG91 dashboard for API limits
- For local webhooks, use ngrok: `ngrok http 8081`

---

## Next Steps

- See `LOCAL_SETUP.md` for detailed configuration
- See `DEVELOPMENT_PLAN.md` for deployment guide
- Check LiveKit Cloud dashboard for room/agent status
- Monitor Google Cloud Console for Vertex AI usage

---

## Quick Reference

| Service | URL/Port |
|---------|---------|
| Backend API | http://localhost:8081 |
| Frontend | http://localhost:3000 |
| LiveKit Cloud | Your project URL |
| Health Check | http://localhost:8081/health |

**Environment Variables:**
- Backend reads from `config/.env`
- Agent reads from `config/.env`
- Frontend uses `VITE_API_URL` or defaults to `http://localhost:8081`



