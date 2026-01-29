import { useState } from 'react';
import axios from 'axios';
import './CallInterface.css';

const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8081';

export default function CallInterface() {
  const [phone, setPhone] = useState('');
  const [language, setLanguage] = useState('en-US');
  const [languageName, setLanguageName] = useState('English');
  const [prompt, setPrompt] = useState('Hello, this is a test call. How can I help you?');
  const [callId, setCallId] = useState(null);
  const [status, setStatus] = useState('');
  const [loading, setLoading] = useState(false);

  const languageMap = {
    'en-US': 'English',
    'ta-IN': 'Tamil',
    'hi-IN': 'Hindi',
    'es-ES': 'Spanish'
  };

  const initiateCall = async () => {
    setLoading(true);
    setStatus('Initiating call...');
    
    try {
      const response = await axios.post(`${API_BASE}/call/initiate`, {
        phone_number: phone,
        language: language,
        language_name: languageName,
        prompt: prompt
      });
      
      if (response.data.success) {
        setCallId(response.data.call_id);
        setStatus(response.data.status || 'Call initiated');
        
        // Poll for status updates
        if (response.data.call_id) {
          pollStatus(response.data.call_id);
        }
      } else {
        setStatus(`Error: ${response.data.error || 'Failed to initiate call'}`);
      }
    } catch (error) {
      setStatus(`Error: ${error.response?.data?.error || error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const pollStatus = async (id) => {
    const interval = setInterval(async () => {
      try {
        const response = await axios.get(`${API_BASE}/call/status?call_id=${id}`);
        if (response.data.success) {
          setStatus(response.data.status);
          
          // Stop polling when call ends
          if (['completed', 'failed', 'cancelled', 'ended'].includes(response.data.status)) {
            clearInterval(interval);
          }
        }
      } catch (error) {
        console.error('Status poll error:', error);
        clearInterval(interval);
      }
    }, 2000);
  };

  return (
    <div className="call-container">
      <h1>Callcenter - Outbound Calling Service</h1>
      <p className="subtitle">Initiate a phone call with AI agent using LiveKit + Gemini</p>
      
      <div className="form-group">
        <label>Phone Number:</label>
        <input
          type="text"
          value={phone}
          onChange={(e) => setPhone(e.target.value)}
          placeholder="+919876543210"
        />
      </div>

      <div className="form-group">
        <label>Language:</label>
        <select
          value={language}
          onChange={(e) => {
            setLanguage(e.target.value);
            setLanguageName(languageMap[e.target.value] || 'English');
          }}
        >
          <option value="en-US">English</option>
          <option value="ta-IN">Tamil</option>
          <option value="hi-IN">Hindi</option>
          <option value="es-ES">Spanish</option>
        </select>
      </div>

      <div className="form-group">
        <label>Agent Prompt:</label>
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          placeholder="Enter the prompt for the AI agent..."
        />
      </div>

      <button
        onClick={initiateCall}
        disabled={loading || !phone || !prompt}
        className="call-button"
      >
        {loading ? 'Calling...' : 'Initiate Call'}
      </button>

      {callId && (
        <div className="status-box">
          <p><strong>Call ID:</strong> {callId}</p>
          <p><strong>Status:</strong> <span className="status-text">{status}</span></p>
        </div>
      )}

      {status && status.includes('Error') && (
        <div className="error-box">
          {status}
        </div>
      )}
    </div>
  );
}




