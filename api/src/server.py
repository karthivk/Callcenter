# api/src/server.py
import json
import os
import uuid
import asyncio
import logging
import time
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

# Generate unique room name based on phone number (matches dispatch rule pattern: call_<caller-number>)
async def generate_room_name(phone_number: str) -> str:
    """Generate LiveKit room name from phone number to match dispatch rule pattern: call_<caller-number>
    
    Note: For inbound SIP calls, the 'caller-number' is the Twilio number making the SIP call to LiveKit,
    not the end user's number. This matches the dispatch rule pattern.
    """
    from livekit.api import LiveKitAPI
    from livekit.api import ListRoomsRequest
    
    # Clean phone number: remove +, spaces, dashes, parentheses
    phone_cleaned = phone_number.replace('+', '').replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
    
    # Base room name: call_<phone-number>
    # This should match the dispatch rule pattern: call_<caller-number>
    base_name = f"call_{phone_cleaned}"
    
    # Log which number is being used (for debugging)
    logging.info(f"📋 [generate_room_name] Using phone number: {phone_number} -> cleaned: {phone_cleaned} -> room name: {base_name}")
    
    # Check for existing rooms with this name (in case same number calls multiple times)
    lk_api = LiveKitAPI(LIVEKIT_HTTP, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
    try:
        resp = await lk_api.room.list_rooms(ListRoomsRequest())
        existing = set(r.name for r in resp.rooms)
    finally:
        await lk_api.aclose()
    
    # If room with this name doesn't exist, use it
    if base_name not in existing:
        return base_name
    
    # If room exists (same number calling again), append timestamp to make it unique
    # Format: call_<phone-number>_<timestamp>
    timestamp = int(time.time())
    unique_name = f"{base_name}_{timestamp}"
    
    # Check if this unique name also exists (extremely unlikely)
    if unique_name not in existing:
        return unique_name
    
    # Fallback: append UUID if still collision (extremely unlikely)
    return f"{base_name}_{uuid.uuid4().hex[:8]}"

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
        
        # Generate call ID
        call_id = str(uuid.uuid4())
        
        # Dispatch rule will automatically create room when SIP call arrives
        # Room name will be: call_<caller-number> where caller-number is from SIP call
        if not TWILIO_PHONE_NUMBER:
            return jsonify(success=False, error="TWILIO_PHONE_NUMBER not configured"), 500
        
        # Clean phone number for Twilio (E.164 format)
        phone_cleaned = phone_number
        if not phone_cleaned.startswith('+'):
            phone_cleaned = '+' + phone_cleaned.lstrip('+').replace(' ', '').replace('-', '')
        
        # Clean Twilio number for room name prediction (for config storage)
        twilio_cleaned = TWILIO_PHONE_NUMBER.replace('+', '').replace(' ', '').replace('-', '')
        predicted_room_name = f"call_{twilio_cleaned}"
        
        app.logger.info(f"📋 [initiate_call] Twilio number (caller): {TWILIO_PHONE_NUMBER}")
        app.logger.info(f"📋 [initiate_call] End user number (called): {phone_number}")
        app.logger.info(f"📋 [initiate_call] Predicted room name: {predicted_room_name} (will be created by dispatch rule)")
        
        # Store call info in memory (by call_id)
        call_status[call_id] = {
            'status': 'initiating',
            'phone': phone_number,
            'language': language,
            'language_name': language_name,
            'prompt': prompt,
            'room_name': predicted_room_name,  # Predicted, actual will be created by dispatch rule
            'twilio_call_sid': None,
            'created_at': datetime.now().isoformat()
        }
        
        # Store call config by predicted room name for agent lookup
        # The dispatch rule will create a room with name like call_<caller-number>
        # We predict it will be call_<twilio-number> based on the SIP caller
        room_config[predicted_room_name] = {
            'phone': phone_number,
            'language': language,
            'language_name': language_name,
            'prompt': prompt,
            'call_id': call_id
        }
        
        app.logger.info(f"📞 [initiate_call] Initiating call: {phone_number}")
        app.logger.info(f"📋 [initiate_call] Room will be created automatically by dispatch rule when SIP call arrives")
        app.logger.info(f"📋 [initiate_call] Dispatch rule pattern: call_<caller-number>")
        
        # Note: We don't pre-create the room anymore
        # The dispatch rule will automatically create the room when the SIP call arrives
        # The room name will be generated by LiveKit based on the dispatch rule's room_prefix
        # and the caller number from the SIP call
        # The agent will be automatically dispatched by the dispatch rule's room_config
        
        # Initiate Twilio outbound call
        if not twilio_client:
            app.logger.warning("⚠️ Twilio credentials not configured, skipping call initiation")
            return jsonify(
                success=True,
                call_id=call_id,
                predicted_room_name=predicted_room_name,
                status='ready',
                message='Ready for call. Room will be created automatically by dispatch rule when call arrives.'
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
        
        webhook_url = f"{api_base}/webhook/twilio/answer?call_id={call_id}"
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
                predicted_room_name=predicted_room_name,  # Room will be created by dispatch rule
                twilio_call_sid=call.sid,
                status='queued',
                message='Call initiated successfully. Room will be created automatically by dispatch rule.'
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
        call_sid = request.form.get('CallSid')
        
        app.logger.info(f"📥 [twilio_answer] Call answered: {call_sid}, Call ID: {call_id}")
        app.logger.info(f"📥 [twilio_answer] Request args: {dict(request.args)}")
        app.logger.info(f"📥 [twilio_answer] Request form: {dict(request.form)}")
        app.logger.info(f"📥 [twilio_answer] Dispatch rule will create room automatically when SIP call arrives")
        
        if call_id and call_id in call_status:
            call_status[call_id]['status'] = 'answered'
        
        # If LiveKit SIP endpoint is configured, connect via SIP
        # NEW APPROACH: Don't specify room name in SIP URI - let dispatch rule create and route
        if LIVEKIT_SIP_ENDPOINT:
            # Create TwiML to dial LiveKit SIP endpoint
            # Format: sip:@livekit_sip_endpoint (no room name - dispatch rule will handle routing)
            # Remove any protocol prefix if present
            sip_endpoint = LIVEKIT_SIP_ENDPOINT.strip()
            if sip_endpoint.startswith('sip:'):
                sip_endpoint = sip_endpoint[4:]
            if sip_endpoint.startswith('@'):
                sip_endpoint = sip_endpoint[1:]
            
            # Get phone number from call status for logging
            phone_number = None
            if call_id and call_id in call_status:
                phone_number = call_status[call_id].get('phone', '')
            
            # SIP URI: Just the endpoint - dispatch rule will create room and route based on caller number
            # The dispatch rule pattern call_<caller-number> will be used to create the room
            sip_uri = f"@{sip_endpoint}"
            
            app.logger.info(f"✅ [twilio_answer] Connecting to LiveKit SIP: sip:{sip_uri}")
            app.logger.info(f"📋 [twilio_answer] SIP endpoint: {sip_endpoint}, Phone: {phone_number}")
            app.logger.info(f"📋 [twilio_answer] Dispatch rule will create room automatically based on caller number")
            app.logger.info(f"📋 [twilio_answer] Expected room name pattern: call_<caller-number>")
            
            response = VoiceResponse()
            dial = Dial(
                timeout=30,  # Wait up to 30 seconds for connection
                action=f"{API_BASE_URL}/webhook/twilio/dial-status?call_id={call_id}",
                method='POST',
                hangupOnStar=False,
                record=False
            )
            # Add SIP URI - just the endpoint, no room name
            # Dispatch rule will automatically create room and dispatch agent
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

@app.route("/webhook/twilio/dial-status", methods=["POST"])
def twilio_dial_status():
    """Handle Twilio dial status callbacks (for SIP connection)"""
    try:
        data = request.form.to_dict()
        call_id = request.args.get('call_id')
        dial_call_status = data.get('DialCallStatus')
        dial_call_sid = data.get('DialCallSid')
        dial_call_duration = data.get('DialCallDuration')
        
        app.logger.info(f"📥 [twilio_dial_status] Dial status: {dial_call_status}, Call ID: {call_id}")
        app.logger.info(f"📥 [twilio_dial_status] Dial Call SID: {dial_call_sid}, Duration: {dial_call_duration}")
        app.logger.info(f"📥 [twilio_dial_status] Full data: {data}")
        
        if dial_call_status == 'failed':
            app.logger.error(f"❌ [twilio_dial_status] SIP connection failed for call {call_id}")
            if call_id and call_id in call_status:
                call_status[call_id]['status'] = 'sip_failed'
        
        # Return empty TwiML (call continues)
        response = VoiceResponse()
        return Response(str(response), mimetype='text/xml')
        
    except Exception as e:
        app.logger.exception(f"❌ [twilio_dial_status] Error: {e}")
        response = VoiceResponse()
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
