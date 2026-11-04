import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState } from 'react-native';
import { useFocusEffect } from 'expo-router';
import {
  cancelVoiceTyping, startVoiceTyping, stopVoiceTyping, subscribeVoiceTyping,
  voiceError, voiceTypingSupported,
} from '../engine/voice';
import { VoiceDraftSession } from '../engine/voicecore';

export function useVoiceTyping(value: string, onChange: (text: string) => void, language: string) {
  const session = useRef<VoiceDraftSession | null>(null);
  const callback = useRef(onChange);
  const [phase, setPhase] = useState<'idle' | 'starting' | 'listening' | 'processing'>('idle');
  const [error, setError] = useState('');
  useEffect(() => { callback.current = onChange; }, [onChange]);

  const cancel = useCallback((discard = false) => {
    const current = session.current;
    if (!current) return;
    current.cancel();
    session.current = null;
    cancelVoiceTyping(current.id);
    if (discard) callback.current(current.base);
    setPhase('idle');
  }, []);

  useFocusEffect(useCallback(() => () => cancel(), [cancel]));

  useEffect(() => {
    const unsubscribe = subscribeVoiceTyping((event) => {
      const current = session.current;
      const accepted = current?.accept(event);
      if (!current || !accepted) return;
      if (accepted.text !== undefined) callback.current(accepted.text);
      if (accepted.terminal) {
        session.current = null;
        setPhase('idle');
        if (event.status === 'error') setError(voiceError(event.code));
      } else if (event.status === 'processing') setPhase('processing');
      else setPhase('listening');
    });
    const background = AppState.addEventListener('change', (state) => {
      if (state !== 'active') cancel();
    });
    return () => {
      unsubscribe();
      background.remove();
      const current = session.current;
      if (current) { current.cancel(); cancelVoiceTyping(current.id); session.current = null; }
    };
  }, [cancel]);

  const start = useCallback(async () => {
    if (session.current) return;
    const current = new VoiceDraftSession(`voice-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`, value);
    session.current = current;
    setError('');
    setPhase('starting');
    try {
      await startVoiceTyping(language === 'tr' ? 'tr-TR' : '', current.id,
        () => session.current === current && current.active);
      if (session.current === current && current.active) {
        setPhase((previous) => previous === 'starting' ? 'listening' : previous);
      }
    } catch (failure) {
      if (session.current !== current) return;
      current.cancel();
      session.current = null;
      cancelVoiceTyping(current.id);
      setPhase('idle');
      const code = failure && typeof failure === 'object' && 'code' in failure ? String(failure.code) : undefined;
      setError(voiceError(code));
    }
  }, [value, language]);

  const stop = useCallback(() => {
    const current = session.current;
    if (!current) return;
    setPhase('processing');
    stopVoiceTyping(current.id);
  }, []);

  return { supported: voiceTypingSupported(), phase, error, permissionDenied: error === voiceError('permission'), active: phase !== 'idle', start, stop, cancel };
}
