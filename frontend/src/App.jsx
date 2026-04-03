import { useState, useEffect, useCallback, useRef } from 'react';
import { useWebRTC } from './hooks/useWebRTC';

function MaterialIcon({ name, size = 22 }) {
  return <span className="material-icons-round" style={{ fontSize: size }}>{name}</span>;
}

function Lobby({ onJoin }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [joining, setJoining] = useState(false);
  const [resumePreview, setResumePreview] = useState('');
  const [sessionId, setSessionId] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef(null);

  const handleFile = async (selectedFile) => {
    if (!selectedFile) return;
    setFile(selectedFile);
    setUploading(true);

    try {
      const formData = new FormData();
      formData.append('resume', selectedFile);

      const res = await fetch('/upload-resume', { method: 'POST', body: formData });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Upload failed');
      }
      const data = await res.json();
      setSessionId(data.session_id);
      setResumePreview(data.preview);
    } catch (e) {
      alert('Failed to upload resume: ' + e.message);
      setFile(null);
    } finally {
      setUploading(false);
    }
  };

  const handleJoin = () => {
    setJoining(true);
    onJoin(sessionId);
  };

  const handleDrop = (e) => {
    e.preventDefault();
    setDragOver(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) handleFile(droppedFile);
  };

  return (
    <div className="h-screen flex items-center justify-center gap-12 p-6 flex-wrap">
      {/* Left: preview area */}
      <div className="w-[480px] max-w-full flex flex-col gap-4">
        {/* Resume upload zone */}
        <div
          className={`h-[280px] bg-[#3c4043] rounded-2xl flex flex-col items-center justify-center relative cursor-pointer border-2 border-dashed transition-colors ${dragOver ? 'border-[#1a73e8] bg-[#1a73e8]/10' : 'border-[#5f6368]'}`}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt,.doc,.docx"
            className="hidden"
            onChange={(e) => handleFile(e.target.files[0])}
          />

          {uploading ? (
            <>
              <div className="w-10 h-10 border-4 border-[#1a73e8] border-t-transparent rounded-full animate-spin mb-3" />
              <p className="text-sm text-[#9aa0a6]">Processing resume...</p>
            </>
          ) : file ? (
            <>
              <div className="w-16 h-16 rounded-full bg-[#34a853]/20 flex items-center justify-center mb-3">
                <MaterialIcon name="check_circle" size={36} />
              </div>
              <p className="text-sm text-[#e8eaed] font-medium">{file.name}</p>
              <p className="text-xs text-[#9aa0a6] mt-1 max-w-[80%] text-center overflow-hidden" style={{ display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical' }}>
                {resumePreview}
              </p>
              <p className="text-xs text-[#669df6] mt-2 hover:underline">Click to change</p>
            </>
          ) : (
            <>
              <div className="w-16 h-16 rounded-full bg-[#3c4043] border-2 border-[#5f6368] flex items-center justify-center mb-3">
                <MaterialIcon name="upload_file" size={32} />
              </div>
              <p className="text-sm text-[#e8eaed] font-medium">Upload your resume</p>
              <p className="text-xs text-[#9aa0a6] mt-1">PDF or TXT — drag & drop or click</p>
            </>
          )}
        </div>

        {/* Mic preview */}
        <div className="flex items-center gap-3 bg-[#3c4043] rounded-xl px-4 py-3">
          <div className="w-9 h-9 rounded-full bg-[#ee675c] flex items-center justify-center text-base font-medium text-[#202124]">
            Y
          </div>
          <div className="flex-1">
            <p className="text-sm text-[#e8eaed]">You</p>
            <p className="text-xs text-[#9aa0a6]">Microphone will be used</p>
          </div>
          <div className="w-9 h-9 rounded-full bg-[#3c4043] border border-[#5f6368] flex items-center justify-center text-[#e8eaed]">
            <MaterialIcon name="mic" size={18} />
          </div>
        </div>
      </div>

      {/* Right: join info */}
      <div className="flex flex-col items-start gap-2 max-w-[320px]">
        <h1 className="text-[28px] font-normal text-[#e8eaed]">Ready to interview?</h1>
        <p className="text-sm text-[#9aa0a6] mb-2">vocat-ai-interview</p>
        <p className="text-xs text-[#9aa0a6] mb-4 leading-relaxed">
          Upload your resume and click join. The AI interviewer will greet you and conduct a live voice interview based on your experience.
        </p>
        <button
          onClick={handleJoin}
          disabled={!sessionId || joining}
          className="bg-[#1a73e8] hover:bg-[#1765cc] disabled:bg-[#3c4043] disabled:text-[#5f6368] text-white border-none rounded-3xl px-6 py-2.5 text-[15px] font-medium cursor-pointer flex items-center gap-2 disabled:cursor-not-allowed transition-colors"
        >
          <MaterialIcon name="call" size={18} />
          {joining ? 'Joining...' : !sessionId ? 'Upload resume first' : 'Join now'}
        </button>
      </div>
    </div>
  );
}

function CallView({ status, onLeave }) {
  const [clock, setClock] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [micMuted, setMicMuted] = useState(false);
  const isSpeaking = status === 'speaking';

  useEffect(() => {
    const update = () => setClock(new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    update();
    const id = setInterval(update, 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);

  const formatTime = (s) => {
    const h = Math.floor(s / 3600);
    const m = String(Math.floor((s % 3600) / 60)).padStart(2, '0');
    const sec = String(s % 60).padStart(2, '0');
    return h > 0 ? `${h}:${m}:${sec}` : `${m}:${sec}`;
  };

  return (
    <div className="h-screen flex flex-col text-[#e8eaed]">
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 h-14 shrink-0">
        <div className="flex items-center gap-4">
          <span className="text-sm">{clock}</span>
          <span className="text-[#5f6368] text-sm">|</span>
          <span className="text-sm">vocat-ai-interview</span>
        </div>
      </div>

      {/* Main call area */}
      <div className="flex-1 flex items-center justify-center px-2 pb-1 relative min-h-0">
        {/* AI main tile */}
        <div className="w-full h-full bg-[#3c4043] rounded-lg flex items-center justify-center relative overflow-hidden">
          <div className="flex flex-col items-center gap-4">
            <div
              className={`w-32 h-32 rounded-full bg-[#669df6] flex items-center justify-center text-[52px] font-medium text-[#1a1a2e] transition-shadow duration-300 ${isSpeaking ? 'animate-[speak-pulse_1.5s_ease-in-out_infinite]' : ''}`}
            >
              AI
            </div>
            {isSpeaking && (
              <div className="flex items-center gap-1">
                {[...Array(5)].map((_, i) => (
                  <div
                    key={i}
                    className="w-1 bg-[#669df6] rounded-full animate-[bar-bounce_0.8s_ease-in-out_infinite]"
                    style={{
                      height: `${12 + Math.random() * 16}px`,
                      animationDelay: `${i * 0.1}s`,
                    }}
                  />
                ))}
              </div>
            )}
          </div>
          <span className="absolute bottom-2 left-2 text-xs font-medium bg-black/55 px-1.5 py-0.5 rounded">
            Interviewer
          </span>
          <div className="absolute bottom-2 right-2 w-7 h-7 rounded-full bg-black/55 flex items-center justify-center">
            <MaterialIcon name="mic" size={16} />
          </div>
        </div>

        {/* Self PiP */}
        <div className="absolute top-3 right-3 w-44 h-[100px] bg-[#3c4043] rounded-lg flex items-center justify-center z-5 overflow-hidden">
          <div
            className={`w-12 h-12 rounded-full bg-[#ee675c] flex items-center justify-center text-xl font-medium text-[#202124] transition-shadow duration-300 ${!micMuted ? 'animate-[self-pulse_1.5s_ease-in-out_infinite]' : ''}`}
          >
            Y
          </div>
          <span className="absolute bottom-1.5 left-1.5 text-[11px] bg-black/55 px-1 py-0.5 rounded">
            You
          </span>
        </div>
      </div>

      {/* Bottom bar */}
      <div className="flex items-center justify-between px-4 h-20 shrink-0">
        <div className="flex items-center gap-2 flex-1">
          <span className="text-[13px]">{formatTime(elapsed)}</span>
          <span className="w-2 h-2 rounded-full bg-[#34a853]" />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setMicMuted(!micMuted)}
            className={`w-12 h-12 rounded-full border-none cursor-pointer flex items-center justify-center transition-colors duration-150 ${micMuted ? 'bg-[#ea4335] hover:bg-[#d93025] text-white' : 'bg-[#3c4043] hover:bg-[#505356] text-[#e8eaed]'}`}
          >
            <MaterialIcon name={micMuted ? 'mic_off' : 'mic'} />
          </button>

          <button
            onClick={onLeave}
            className="w-14 h-10 rounded-3xl border-none bg-[#ea4335] hover:bg-[#d93025] text-white cursor-pointer flex items-center justify-center transition-colors duration-150"
          >
            <MaterialIcon name="call_end" />
          </button>
        </div>

        <div className="flex-1" />
      </div>
    </div>
  );
}

function App() {
  const { status, error, start, stop } = useWebRTC();
  const [inCall, setInCall] = useState(false);

  const handleJoin = useCallback((sessionId) => {
    start(sessionId);
    setInCall(true);
  }, [start]);

  const handleLeave = useCallback(() => {
    stop();
    setInCall(false);
  }, [stop]);

  useEffect(() => {
    if (inCall && (status === 'error' || status === 'disconnected')) {
      const t = setTimeout(() => {
        if (status === 'error' || status === 'disconnected') {
          setInCall(false);
        }
      }, 2000);
      return () => clearTimeout(t);
    }
  }, [status, inCall]);

  if (!inCall) {
    return (
      <div className="text-[#e8eaed]">
        <Lobby onJoin={handleJoin} />
        {error && (
          <div className="fixed bottom-6 left-1/2 -translate-x-1/2 bg-[#323232] text-[#e8eaed] text-sm px-5 py-3 rounded-lg shadow-lg z-50">
            {error}
          </div>
        )}
      </div>
    );
  }

  return <CallView status={status} onLeave={handleLeave} />;
}

export default App;
