# agents/src/gemini_agent.py
import asyncio
import json
import logging
import os
from pathlib import Path
from dotenv import load_dotenv
from livekit import agents, rtc
from livekit.agents import AgentSession, VoiceAssistantAgent
from livekit.plugins import google, noise_cancellation

# Load environment variables from config/.env
env_path = Path(__file__).parent.parent.parent / "config" / ".env"
load_dotenv(env_path)

logging.basicConfig(level=logging.INFO)

async def entrypoint(ctx: agents.JobContext):
    """Minimal agent for MSG91 phone calls"""
    logging.info(f"📞 Agent connecting to room: {ctx.room.name}")
    
    # Get call configuration from room metadata
    room_metadata = ctx.room.metadata or "{}"
    try:
        metadata = json.loads(room_metadata)
        language = metadata.get('language', 'en-US')
        language_name = metadata.get('language_name', 'English')
        prompt = metadata.get('prompt', 'You are a helpful assistant.')
        phone = metadata.get('phone', 'unknown')
        call_id = metadata.get('call_id', 'unknown')
        
        logging.info(f"📞 Call config - Phone: {phone}, Language: {language_name}, Call ID: {call_id}")
    except Exception as e:
        # Fallback to environment variables or defaults
        language = os.getenv("CALL_LANGUAGE", "en-US")
        language_name = os.getenv("CALL_LANGUAGE_NAME", "English")
        prompt = os.getenv("CALL_PROMPT", "You are a helpful assistant.")
        logging.warning(f"⚠️ Could not parse room metadata: {e}, using defaults")
    
    # Determine voice based on language
    voice_map = {
        'en-US': 'Leda',
        'ta-IN': 'Leda',
        'hi-IN': 'Leda',
        'es-ES': 'Charon'
    }
    voice = voice_map.get(language, 'Leda')
    
    # Create LLM model
    llm = google.beta.realtime.RealtimeModel(
        model="gemini-live-2.5-flash-native-audio",
        vertexai=True,
        project=os.getenv("GCP_PROJECT_ID"),
        location=os.getenv("VERTEX_AI_LOCATION", "us-central1"),
        voice=voice,
        language=language,
        instructions=(
            f"You are a helpful assistant speaking in {language_name}. "
            f"{prompt} "
            "Keep responses concise and natural for phone conversations. "
            "Speak clearly and wait for the user to finish before responding."
        ),
        temperature=0.6,
        top_p=0.9,
        top_k=40,
    )
    
    logging.info(f"✅ RealtimeModel created - Language: {language_name}, Voice: {voice}")
    
    # Create agent with the LLM (VoiceAssistantAgent creates session internally)
    agent = VoiceAssistantAgent(
        llm=llm,
        room_input_options=agents.RoomInputOptions(
            text_enabled=True,
            video_enabled=False,
            noise_cancellation=noise_cancellation.BVCTelephony(),  # Important for phone calls
        )
    )
    
    # Start the agent in the room
    await agent.start(ctx.room)
    
    logging.info("✅ Agent started")
    
    # Wait for connection
    await ctx.connect()
    
    # Generate initial greeting using the agent's session
    greeting = f"Hello, this is an AI assistant calling you. How can I help you today?"
    await agent.session.generate_reply(instructions=greeting)
    
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


