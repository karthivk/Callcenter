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
from livekit.protocol.room import CreateRoomRequest, UpdateRoomMetadataRequest

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
room_config = {}  # {room_name: {'phone': '...', 'language': '...', 'language_name': '...', 'prompt': '...', 'call_id': '...'}}

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

# Generate unique room name (with collision check like Companion project)
async def generate_room_name() -> str:
    """Generate unique LiveKit room name, checking against existing rooms"""
    from livekit.api import LiveKitAPI
    from livekit.api import ListRoomsRequest
    
    lk_api = LiveKitAPI(LIVEKIT_HTTP, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        # Get list of existing rooms
        resp = await lk_api.room.list_rooms(ListRoomsRequest())
        existing = set(r.name for r in resp.rooms)
    finally:
        await lk_api.aclose()
    
    # Generate unique name (check for collisions)
    max_attempts = 10
    for _ in range(max_attempts):
        name = f"call_{uuid.uuid4().hex[:8]}"
        if name not in existing:
            return name
        app.logger.warning(f"⚠️ Room name collision detected: {name}, generating new name...")
    
    # Fallback: use longer UUID if collisions persist (extremely unlikely)
    return f"call_{uuid.uuid4().hex[:16]}"

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
        
        # Generate call ID and room name (with collision check)
        call_id = str(uuid.uuid4())
        
        # Generate room name (async, so run in thread)
        def get_room_name():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            try:
                return new_loop.run_until_complete(generate_room_name())
            finally:
                new_loop.close()
        
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(get_room_name)
            room_name = future.result(timeout=5)
        
        # Clean phone number for Twilio (E.164 format)
        phone_cleaned = phone_number
        if not phone_cleaned.startswith('+'):
            phone_cleaned = '+' + phone_cleaned.lstrip('+').replace(' ', '').replace('-', '')
        
        # Store call info in memory (by call_id)
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
        
        # Store call config by room_name for agent lookup (simpler than room metadata)
        room_config[room_name] = {
            'phone': phone_number,
            'language': language,
            'language_name': language_name,
            'prompt': prompt,
            'call_id': call_id
        }
        
        app.logger.info(f"📞 [initiate_call] Initiating call: {phone_number} -> {room_name}")
        
        # Create LiveKit room with metadata using REST API (synchronous HTTP)
        try:
            # Create room with metadata
            room_metadata = json.dumps({
                "call_id": call_id,
                "phone": phone_number,
                "language": language,
                "language_name": language_name,
                "prompt": prompt
            })
            
            # Use LiveKit SDK to create room
            # Always use thread-based approach to completely isolate from Flask
            def create_room_in_thread():
                """Create room in a separate thread with its own event loop"""
                # Create a completely new event loop in this thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    async def create_room_async():
                        """Create LiveKit room with agent dispatch"""
                        # Create LiveKit API client inside async context
                        lk_api = LiveKitAPI(LIVEKIT_HTTP, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
                        try:
                            # Create room using CreateRoomRequest
                            # Set fields directly on the request object
                            request = CreateRoomRequest()
                            request.name = room_name
                            request.metadata = room_metadata
                            
                            # Add agent dispatch directly to agents field
                            agent = RoomAgentDispatch(agent_name=LIVEKIT_AGENT_NAME)
                            request.agents.append(agent)
                            
                            room = await lk_api.room.create_room(request)
                            
                            # Update room metadata after creation to ensure it's persisted
                            # Sometimes metadata needs to be set after room creation
                            try:
                                update_request = UpdateRoomMetadataRequest()
                                update_request.room = room_name
                                update_request.metadata = room_metadata
                                await lk_api.room.update_room_metadata(update_request)
                                logging.info(f"✅ [initiate_call] Room metadata updated after creation")
                            except Exception as update_error:
                                # Log but don't fail if update fails - metadata should still be set on creation
                                logging.warning(f"⚠️ Could not update room metadata (this is OK if metadata was set on creation): {update_error}")
                            
                            return room
                        finally:
                            await lk_api.aclose()
                    
                    # Run async function in the new event loop
                    return new_loop.run_until_complete(create_room_async())
                finally:
                    new_loop.close()
            
            # Execute in thread to completely isolate from Flask's event loop
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(create_room_in_thread)
                room = future.result(timeout=10)
            
            # Log room details to verify metadata was set
            app.logger.info(f"✅ [initiate_call] LiveKit room created: {room_name} with agent: {LIVEKIT_AGENT_NAME}")
            app.logger.info(f"📋 [initiate_call] Room metadata set: {room_metadata}")
            if hasattr(room, 'metadata'):
                app.logger.info(f"📋 [initiate_call] Room metadata (from response): {room.metadata}")
            if hasattr(room, 'name'):
                app.logger.info(f"📋 [initiate_call] Room name (from response): {room.name}")
            
        except Exception as e:
            app.logger.error(f"❌ [initiate_call] LiveKit room creation error: {e}")
            import traceback
            app.logger.error(traceback.format_exc())
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
        # Validate and fix API_BASE_URL if needed
        api_base = API_BASE_URL.strip().rstrip('/')
        if not api_base.startswith(('http://', 'https://')):
            app.logger.error(f"❌ [initiate_call] Invalid API_BASE_URL: {API_BASE_URL} (must start with http:// or https://)")
            return jsonify(
                success=False,
                error=f"Invalid API_BASE_URL configuration: {API_BASE_URL}",
                call_id=call_id
            ), 500
        
        webhook_url = f"{api_base}/webhook/twilio/answer?call_id={call_id}&room_name={room_name}"
        status_callback = f"{api_base}/webhook/twilio/status"
        
        app.logger.info(f"📞 [initiate_call] Webhook URL: {webhook_url}")
        
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
        
        app.logger.info(f"📥 [twilio_answer] Call answered: {call_sid}, Room: {room_name}, Call ID: {call_id}")
        app.logger.info(f"📥 [twilio_answer] Request args: {dict(request.args)}")
        app.logger.info(f"📥 [twilio_answer] Request form: {dict(request.form)}")
        
        if call_id and call_id in call_status:
            call_status[call_id]['status'] = 'answered'
        
        # Validate room_name
        if not room_name:
            app.logger.error("❌ [twilio_answer] Missing room_name in request")
            response = VoiceResponse()
            response.say("Sorry, there was an error connecting the call. Missing room information.")
            return Response(str(response), mimetype='text/xml')
        
        # If LiveKit SIP endpoint is configured, connect via SIP
        if LIVEKIT_SIP_ENDPOINT:
            # Create TwiML to dial LiveKit SIP endpoint
            # Format: sip:room_name@livekit_sip_endpoint
            # Remove any protocol prefix if present
            sip_endpoint = LIVEKIT_SIP_ENDPOINT.strip()
            if sip_endpoint.startswith('sip:'):
                sip_endpoint = sip_endpoint[4:]
            if sip_endpoint.startswith('@'):
                sip_endpoint = sip_endpoint[1:]
            
            sip_uri = f"{room_name}@{sip_endpoint}"
            
            app.logger.info(f"✅ [twilio_answer] Connecting to LiveKit SIP: sip:{sip_uri}")
            
            response = VoiceResponse()
            dial = Dial()
            dial.sip(sip_uri)
            response.append(dial)
            
            twiml_xml = str(response)
            app.logger.info(f"📤 [twilio_answer] TwiML Response:\n{twiml_xml}")
            
            return Response(twiml_xml, mimetype='text/xml')
        else:
            # Fallback: Just say something (for testing without SIP)
            app.logger.warning("⚠️ [twilio_answer] LIVEKIT_SIP_ENDPOINT not configured, using fallback")
            response = VoiceResponse()
            response.say("Connecting to AI assistant. Please wait.")
            return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        app.logger.exception(f"❌ [twilio_answer] Error: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
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

@app.route("/call/config", methods=["GET"])
def get_call_config():
    """Get call configuration by room name (for agent)"""
    room_name = request.args.get('room_name')
    
    if not room_name or room_name not in room_config:
        return jsonify(success=False, error="Room config not found"), 404
    
    config = room_config[room_name]
    return jsonify(
        success=True,
        room_name=room_name,
        phone=config['phone'],
        language=config['language'],
        language_name=config['language_name'],
        prompt=config['prompt'],
        call_id=config['call_id']
    )

if __name__ == '__main__':
    app.run(port=PORT, debug=False)  # debug=False to avoid event loop conflicts with asyncio.run()
