# agents/src/gemini_agent.py
import asyncio
import logging
import os
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
import httpx
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
    
    # Fetch call configuration from backend API using room name
    api_base_url = os.getenv("API_BASE_URL", "http://localhost:8081")
    room_name = ctx.room.name
    
    # Default values (fallback if API call fails)
    language = os.getenv("CALL_LANGUAGE", "en-US")
    language_name = os.getenv("CALL_LANGUAGE_NAME", "English")
    prompt = os.getenv("CALL_PROMPT", "You are a helpful assistant.")
    
    # Try to fetch config from API
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            config_url = f"{api_base_url}/call/config?room_name={room_name}"
            logging.info(f"📞 Fetching call config from: {config_url}")
            response = await client.get(config_url)
            
            if response.status_code == 200:
                config_data = response.json()
                if config_data.get("success"):
                    language = config_data.get("language", language)
                    language_name = config_data.get("language_name", language_name)
                    prompt = config_data.get("prompt", prompt)
                    logging.info(f"✅ [agent] Fetched config from API - Language: {language_name}, Prompt: {prompt[:50]}...")
                else:
                    logging.warning(f"⚠️ [agent] API returned success=false, using defaults")
            else:
                logging.warning(f"⚠️ [agent] API returned status {response.status_code}, using defaults")
    except Exception as e:
        logging.warning(f"⚠️ [agent] Failed to fetch config from API: {e}, using defaults")
    
    logging.info(f"📞 Call config - Language: {language_name}, Prompt: {prompt[:50]}...")
    
    # Determine voice based on language
    voice_map = {
        'en-US': 'Leda',
        'ta-IN': 'Leda',
        'hi-IN': 'Leda',
        'es-ES': 'Charon'
    }
    voice = voice_map.get(language, 'Leda')
    
    # Create instructions string
    # Gemini 2.5 doesn't support language parameter - include it in the prompt
    instructions = (
        f"You are a helpful assistant. You MUST speak ONLY in {language_name} ({language}). "
        f"Your role and instructions: {prompt} "
        "Keep responses concise and natural for phone conversations. "
        "Speak clearly and wait for the user to finish before responding. "
        f"Always respond in {language_name}."
    )
    
    # Create LLM model
    # NOTE: Gemini 2.5 doesn't support language parameter - language is included in instructions above
    llm = google.beta.realtime.RealtimeModel(
        model="gemini-live-2.5-flash-native-audio",
        vertexai=True,
        project=os.getenv("GCP_PROJECT_ID"),
        location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        voice=voice,
        # language=language,  # REMOVED: Gemini 2.5 doesn't support this parameter
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
    
    # Generate initial greeting using the prompt from frontend
    # The prompt should guide the conversation - use it as the initial message
    # If prompt already starts with a greeting, use it directly; otherwise create one
    if prompt.strip().lower().startswith(('hello', 'hi', 'greetings', 'good')):
        # Prompt already contains a greeting
        initial_message = prompt
    else:
        # Create a greeting that incorporates the prompt
        initial_message = f"Hello. {prompt}"
    
    await session.generate_reply(instructions=initial_message)
    
    logging.info(f"✅ Initial greeting sent (using prompt from frontend): {initial_message[:50]}...")
    
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


