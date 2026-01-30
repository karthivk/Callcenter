# agents/src/gemini_agent.py
import asyncio
import json
import logging
import os
import requests
from pathlib import Path

# IMPORTANT: Unset GOOGLE_APPLICATION_CREDENTIALS BEFORE any Google imports
# This must happen before importing google.auth or any Google libraries
# to ensure Application Default Credentials (ADC) is used instead of service account key files
if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if creds_path:
        logging.info("⚠️ GOOGLE_APPLICATION_CREDENTIALS is set, unsetting to use ADC instead")
        os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentSession, Agent
from livekit.plugins import google, noise_cancellation

# Load environment variables from config/.env
env_path = Path(__file__).parent.parent.parent / "config" / ".env"
load_dotenv(env_path)

# Unset again after loading .env (in case .env set it)
if os.getenv("GOOGLE_APPLICATION_CREDENTIALS"):
    logging.info("⚠️ GOOGLE_APPLICATION_CREDENTIALS found in .env, unsetting to use ADC")
    os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

logging.basicConfig(level=logging.INFO)

async def entrypoint(ctx: agents.JobContext):
    """Minimal agent for LiveKit phone calls"""
    logging.info(f"📞 Agent connecting to room: {ctx.room.name}")
    
    # Get call configuration from API (simpler than room metadata)
    room_name = ctx.room.name
    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8081")
    
    # Try to fetch call config from API
    language = os.getenv("CALL_LANGUAGE", "en-US")
    language_name = os.getenv("CALL_LANGUAGE_NAME", "English")
    prompt = os.getenv("CALL_PROMPT", "You are a helpful assistant.")
    phone = "unknown"
    call_id = "unknown"
    
    try:
        config_url = f"{api_base_url}/call/config?room_name={room_name}"
        logging.info(f"📞 Fetching call config from: {config_url}")
        response = requests.get(config_url, timeout=5)
        if response.status_code == 200:
            config = response.json()
            if config.get('success'):
                language = config.get('language', language)
                language_name = config.get('language_name', language_name)
                prompt = config.get('prompt', prompt)
                phone = config.get('phone', phone)
                call_id = config.get('call_id', call_id)
                logging.info(f"✅ Call config fetched - Phone: {phone}, Language: {language_name}, Call ID: {call_id}")
            else:
                logging.warning(f"⚠️ API returned success=False: {config.get('error')}")
        else:
            logging.warning(f"⚠️ Failed to fetch call config: HTTP {response.status_code}")
    except Exception as e:
        logging.warning(f"⚠️ Could not fetch call config from API: {e}, using defaults")
    
    logging.info(f"📞 Call config - Phone: {phone}, Language: {language_name}, Call ID: {call_id}, Prompt: {prompt[:50]}...")
    
    # Determine voice based on language
    voice_map = {
        'en-US': 'Leda',
        'ta-IN': 'Leda',
        'hi-IN': 'Leda',
        'es-ES': 'Charon'
    }
    voice = voice_map.get(language, 'Leda')
    
    # Create instructions string
    instructions = (
        f"You are a helpful assistant speaking in {language_name}. "
        f"{prompt} "
        "Keep responses concise and natural for phone conversations. "
        "Speak clearly and wait for the user to finish before responding."
    )
    
    # Create LLM model
    llm = google.beta.realtime.RealtimeModel(
        model="gemini-live-2.5-flash-native-audio",
        vertexai=True,
        project=os.getenv("GCP_PROJECT_ID"),
        location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        voice=voice,
        language=language,
        instructions=instructions,
        temperature=0.6,
        top_p=0.9,
        top_k=40,
    )
    
    logging.info(f"✅ RealtimeModel created - Language: {language_name}, Voice: {voice}")
    
    # Create a minimal agent instance (required by SDK - provides label attribute)
    agent = Agent(llm=llm, instructions=instructions)
    
    # Create session with Gemini Realtime
    session = AgentSession(
        userdata={},
        llm=llm
    )
    
    # Start session with telephony noise cancellation
    await session.start(
        room=ctx.room,
        agent=agent,
        room_input_options=agents.RoomInputOptions(
            text_enabled=True,
            video_enabled=False,
            noise_cancellation=noise_cancellation.BVCTelephony(),  # Important for phone calls
        )
    )
    
    logging.info("✅ Agent session started")
    
    # Wait for connection
    await ctx.connect()
    
    # Generate initial greeting
    greeting = f"Hello, this is an AI assistant calling you. How can I help you today?"
    await session.generate_reply(instructions=greeting)
    
    logging.info("✅ Initial greeting sent")
    
    # Keep agent running until call ends
    # The agent will automatically handle the conversation

def main():
    agent_name = os.getenv("LIVEKIT_AGENT_NAME", "callcenter-agent")
    logging.info(f"🚀 Starting Callcenter agent: {agent_name}")
    
    agents.cli.run_app(agents.WorkerOptions(
        entrypoint_fnc=entrypoint,
        agent_name=agent_name
    ))

if __name__ == "__main__":
    main()


