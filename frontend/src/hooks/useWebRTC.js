import { useState, useRef, useCallback } from 'react';

const ICE_SERVERS = [{ urls: 'stun:stun.l.google.com:19302' }];

export function useWebRTC() {
  const [status, setStatus] = useState('disconnected');
  const [error, setError] = useState(null);

  const pcRef = useRef(null);
  const localStreamRef = useRef(null);
  const audioQueueRef = useRef([]);
  const isPlayingRef = useRef(false);
  const audioElRef = useRef(null);

  const getAudioEl = useCallback(() => {
    if (!audioElRef.current) {
      audioElRef.current = new Audio();
    }
    return audioElRef.current;
  }, []);

  const playNextInQueue = useCallback(() => {
    if (audioQueueRef.current.length > 0 && !isPlayingRef.current) {
      isPlayingRef.current = true;
      const stream = audioQueueRef.current.shift();
      const audio = getAudioEl();
      audio.srcObject = stream;
      setStatus('speaking');

      audio.play().catch(() => {
        isPlayingRef.current = false;
        playNextInQueue();
      });

      audio.onended = () => {
        isPlayingRef.current = false;
        playNextInQueue();
      };
    } else if (audioQueueRef.current.length === 0 && !isPlayingRef.current) {
      setStatus('connected');
    }
  }, [getAudioEl]);

  const start = useCallback(async (sessionId) => {
    setError(null);
    setStatus('connecting');

    try {
      const localStream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
        video: false,
      });
      localStreamRef.current = localStream;

      const pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
      pcRef.current = pc;

      pc.ontrack = (event) => {
        if (event.track.kind === 'audio' && event.streams[0]) {
          audioQueueRef.current.push(event.streams[0]);
          setStatus('speaking');
          playNextInQueue();
        }
      };

      pc.onconnectionstatechange = () => {
        const state = pc.connectionState;
        if (state === 'connected') {
          setStatus('connected');
        } else if (['failed', 'disconnected', 'closed'].includes(state)) {
          setStatus('disconnected');
          stop();
        }
      };

      localStream.getTracks().forEach((track) => pc.addTrack(track, localStream));

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      const response = await fetch('/offer', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sdp: offer.sdp,
          type: offer.type,
          session_id: sessionId || '',
        }),
      });

      if (!response.ok) throw new Error(`Server error: ${response.status}`);

      const answer = await response.json();
      await pc.setRemoteDescription(new RTCSessionDescription(answer));
      setStatus('connected');
    } catch (err) {
      setError(err.message);
      setStatus('error');
      stop();
    }
  }, [playNextInQueue]);

  const stop = useCallback(() => {
    if (pcRef.current) {
      pcRef.current.close();
      pcRef.current = null;
    }
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((t) => t.stop());
      localStreamRef.current = null;
    }
    const audio = getAudioEl();
    audio.srcObject = null;
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    setStatus('disconnected');
  }, [getAudioEl]);

  return { status, error, start, stop };
}
