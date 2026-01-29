# api/src/server.py
import json
import os
import uuid
import asyncio
import logging
import concurrent.futures
from pathlib import Path
from datetime import datetime
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from dotenv import load_dotenv
from twilio.rest import Client as TwilioClient
from twilio.twiml.voice_response import VoiceResponse, Dial
from livekit import api
from livekit.api import LiveKitAPI
from livekit.protocol.agent_dispatch import RoomAgentDispatch
from livekit.protocol.room import RoomConfiguration

# Load environment variables from config/.env
env_path = Path(__file__).parent.parent.parent / "config" / ".env"
load_dotenv(env_path)

def env(key: str, default=None):
    v = os.getenv(key, default)
    if isinstance(v, str):
        v = v.strip()
    return v

# Flask app
app = Flask(__name__)
app.url_map.strict_slashes = False

# Enable CORS
CORS(app, resources={r"/*": {
    "origins": "*",
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization"],
}})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Configuration
LIVEKIT_HTTP = os.getenv("LIVEKIT_HTTP_URL", "").strip()
LIVEKIT_API_KEY = env("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = env("LIVEKIT_API_SECRET", "")
TWILIO_ACCOUNT_SID = env("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = env("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = env("TWILIO_PHONE_NUMBER", "")  # Your Twilio phone number
LIVEKIT_SIP_ENDPOINT = env("LIVEKIT_SIP_ENDPOINT", "")  # LiveKit Cloud SIP endpoint
LIVEKIT_AGENT_NAME = env("LIVEKIT_AGENT_NAME", "callcenter-agent")  # Agent name from .env
API_BASE_URL = env("API_BASE_URL", "https://your-api.run.app")
PORT = int(env("PORT", "8081"))

# Initialize Twilio client
twilio_client = None
if TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN:
    twilio_client = TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# In-memory storage for POC (no database)
call_status = {}  # {call_id: {'status': '...', 'phone': '...', 'language': '...', 'prompt': '...', 'room_name': '...', 'twilio_call_sid': '...'}}

# Health check endpoints
@app.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(status="ok"), 200

@app.route("/health", methods=["GET"])
def health():
    return "ok", 200

@app.route("/", methods=["GET"])
def root():
    return jsonify(service="Callcenter API", version="1.0.0"), 200

# Generate unique room name
def generate_room_name() -> str:
    """Generate unique LiveKit room name"""
    return f"call_{uuid.uuid4().hex[:8]}"

@app.route("/call/initiate", methods=["POST"])
def initiate_call():
    """Initiate Twilio outbound call that connects to LiveKit"""
    try:
        data = request.json
        phone_number = data.get('phone_number')
        language = data.get('language', 'en-US')
        language_name = data.get('language_name', 'English')
        prompt = data.get('prompt')
        
        if not phone_number or not prompt:
            return jsonify(success=False, error="phone_number and prompt required"), 400
        
        # Generate call ID and room name
        call_id = str(uuid.uuid4())
        room_name = generate_room_name()
        
        # Clean phone number for Twilio (E.164 format)
        phone_cleaned = phone_number
        if not phone_cleaned.startswith('+'):
            phone_cleaned = '+' + phone_cleaned.lstrip('+').replace(' ', '').replace('-', '')
        
        # Store call info in memory
        call_status[call_id] = {
            'status': 'initiating',
            'phone': phone_number,
            'language': language,
            'language_name': language_name,
            'prompt': prompt,
            'room_name': room_name,
            'twilio_call_sid': None,
            'created_at': datetime.now().isoformat()
        }
        
        app.logger.info(f"📞 [initiate_call] Initiating call: {phone_number} -> {room_name}")
        
        # Create LiveKit room with metadata
        try:
            lk_api = LiveKitAPI(LIVEKIT_HTTP, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
            
            # Create room with metadata
            room_metadata = json.dumps({
                "call_id": call_id,
                "phone": phone_number,
                "language": language,
                "language_name": language_name,
                "prompt": prompt
            })
            
            # Create room via API with agent dispatch (agent name from .env)
            # Always use a thread with new event loop to avoid conflicts with Flask
            import concurrent.futures
            
            def create_room_async():
                """Run async room creation in a new event loop"""
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    return new_loop.run_until_complete(
                        lk_api.room.create_room(
                            name=room_name,
                            metadata=room_metadata,
                            configuration=RoomConfiguration(
                                agents=[RoomAgentDispatch(agent_name=LIVEKIT_AGENT_NAME)]
                            )
                        )
                    )
                finally:
                    new_loop.close()
            
            # Execute in thread to avoid event loop conflicts
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(create_room_async)
                future.result(timeout=10)
            
            app.logger.info(f"✅ [initiate_call] LiveKit room created: {room_name} with agent: {LIVEKIT_AGENT_NAME}")
            
        except Exception as e:
            app.logger.error(f"❌ [initiate_call] LiveKit room creation error: {e}")
            return jsonify(
                success=False,
                error=f"Failed to create LiveKit room: {str(e)}",
                call_id=call_id
            ), 500
        
        # Initiate Twilio outbound call
        if not twilio_client:
            app.logger.warning("⚠️ Twilio credentials not configured, skipping call initiation")
            return jsonify(
                success=True,
                call_id=call_id,
                room_name=room_name,
                status='room_created',
                message='Room created but Twilio not configured'
            )
        
        if not TWILIO_PHONE_NUMBER:
            return jsonify(
                success=False,
                error="TWILIO_PHONE_NUMBER not configured",
                call_id=call_id
            ), 500
        
        # Webhook URL for when call is answered
        webhook_url = f"{API_BASE_URL}/webhook/twilio/answer?call_id={call_id}&room_name={room_name}"
        status_callback = f"{API_BASE_URL}/webhook/twilio/status"
        
        try:
            # Make outbound call using Twilio Voice API
            call = twilio_client.calls.create(
                to=phone_cleaned,
                from_=TWILIO_PHONE_NUMBER,
                url=webhook_url,
                status_callback=status_callback,
                status_callback_event=['initiated', 'ringing', 'answered', 'completed'],
                status_callback_method='POST',
                method='POST'
            )
            
            call_status[call_id]['twilio_call_sid'] = call.sid
            call_status[call_id]['status'] = 'queued'
            
            app.logger.info(f"✅ [initiate_call] Twilio call initiated: {call.sid}")
            
            return jsonify(
                success=True,
                call_id=call_id,
                room_name=room_name,
                twilio_call_sid=call.sid,
                status='queued',
                message='Call initiated successfully'
            )
                
        except Exception as e:
            app.logger.exception(f"❌ [initiate_call] Twilio call initiation error: {e}")
            call_status[call_id]['status'] = 'failed'
            return jsonify(
                success=False,
                error=f"Failed to initiate call: {str(e)}",
                call_id=call_id
            ), 500
            
    except Exception as e:
        app.logger.exception(f"❌ [initiate_call] Error: {e}")
        return jsonify(success=False, error=str(e)), 500

@app.route("/webhook/twilio/answer", methods=["POST"])
def twilio_answer():
    """Handle Twilio webhook when call is answered - return TwiML to connect to LiveKit"""
    try:
        call_id = request.args.get('call_id')
        room_name = request.args.get('room_name')
        call_sid = request.form.get('CallSid')
        
        app.logger.info(f"📥 [twilio_answer] Call answered: {call_sid}, Room: {room_name}")
        
        if call_id and call_id in call_status:
            call_status[call_id]['status'] = 'answered'
        
        # If LiveKit SIP endpoint is configured, connect via SIP
        if LIVEKIT_SIP_ENDPOINT:
            # Create TwiML to dial LiveKit SIP endpoint
            response = VoiceResponse()
            dial = Dial()
            # Format: sip:room_name@livekit_sip_endpoint
            dial.sip(f"{room_name}@{LIVEKIT_SIP_ENDPOINT}")
            response.append(dial)
            
            app.logger.info(f"✅ [twilio_answer] Connecting to LiveKit SIP: {room_name}@{LIVEKIT_SIP_ENDPOINT}")
            return Response(str(response), mimetype='text/xml')
        else:
            # Fallback: Just say something (for testing without SIP)
            response = VoiceResponse()
            response.say("Connecting to AI assistant. Please wait.")
            app.logger.warning("⚠️ [twilio_answer] LIVEKIT_SIP_ENDPOINT not configured, using fallback")
            return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        app.logger.exception(f"❌ [twilio_answer] Error: {e}")
        response = VoiceResponse()
        response.say("Sorry, there was an error connecting the call.")
        return Response(str(response), mimetype='text/xml')

@app.route("/webhook/twilio/status", methods=["POST"])
def twilio_status():
    """Handle Twilio status callbacks"""
    try:
        data = request.form.to_dict()
        call_sid = data.get('CallSid')
        call_status_twilio = data.get('CallStatus')
        
        app.logger.info(f"📥 [twilio_status] Call status update: {call_sid} -> {call_status_twilio}")
        
        # Find call_id from twilio_call_sid
        call_id = None
        for cid, info in call_status.items():
            if info.get('twilio_call_sid') == call_sid:
                call_id = cid
                break
        
        if call_id and call_id in call_status:
            # Map Twilio status to our status
            status_map = {
                'queued': 'queued',
                'ringing': 'ringing',
                'in-progress': 'connected',
                'completed': 'completed',
                'busy': 'busy',
                'failed': 'failed',
                'no-answer': 'no-answer',
                'canceled': 'cancelled'
            }
            
            new_status = status_map.get(call_status_twilio, call_status_twilio)
            call_status[call_id]['status'] = new_status
            
            app.logger.info(f"✅ [twilio_status] Call {call_id} status updated to: {new_status}")
        
        return Response('', mimetype='text/xml')
        
    except Exception as e:
        app.logger.exception(f"❌ [twilio_status] Error: {e}")
        return Response('', mimetype='text/xml')

@app.route("/call/status", methods=["GET"])
def get_call_status():
    """Get call status"""
    call_id = request.args.get('call_id')
    
    if not call_id or call_id not in call_status:
        return jsonify(success=False, error="Call not found"), 404
    
    return jsonify(
        success=True,
        call_id=call_id,
        status=call_status[call_id]['status'],
        phone=call_status[call_id]['phone'],
        room_name=call_status[call_id].get('room_name'),
        twilio_call_sid=call_status[call_id].get('twilio_call_sid')
    )

if __name__ == '__main__':
    app.run(port=PORT, debug=True)
