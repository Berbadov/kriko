import { NativeEventEmitter, NativeModules, PermissionsAndroid, Platform } from 'react-native';
import type { VoiceEvent } from './voicecore';

interface VoiceNative {
  voiceTypingAvailable(): Promise<boolean>;
  startVoiceTyping(locale: string, sessionId: string): Promise<boolean>;
  stopVoiceTyping(sessionId: string): void;
  cancelVoiceTyping(sessionId: string): void;
  addListener(name: string): void;
  removeListeners(count: number): void;
}

function native(): VoiceNative | undefined {
  return Platform.OS === 'android' ? NativeModules.KrikoOverlay as VoiceNative | undefined : undefined;
}

export function voiceTypingSupported(): boolean {
  return typeof native()?.startVoiceTyping === 'function';
}

export async function startVoiceTyping(locale: string, id: string, stillWanted: () => boolean): Promise<void> {
  const module = native();
  if (!module?.startVoiceTyping || !await module.voiceTypingAvailable()) throw { code: 'unavailable' };
  if (!stillWanted()) return;
  const permission = PermissionsAndroid.PERMISSIONS.RECORD_AUDIO;
  const allowed = await PermissionsAndroid.check(permission) ||
    await PermissionsAndroid.request(permission) === PermissionsAndroid.RESULTS.GRANTED;
  if (!stillWanted()) return;
  if (!allowed) throw { code: 'permission' };
  if (!await module.startVoiceTyping(locale, id)) throw { code: 'unavailable' };
}

export function stopVoiceTyping(id: string): void { native()?.stopVoiceTyping(id); }
export function cancelVoiceTyping(id: string): void { native()?.cancelVoiceTyping(id); }

export function subscribeVoiceTyping(listener: (event: VoiceEvent) => void): () => void {
  const module = native();
  if (!module?.startVoiceTyping) return () => {};
  const subscription = new NativeEventEmitter(module).addListener('onVoiceTyping', (event: unknown) => {
    if (!event || typeof event !== 'object') return;
    const value = event as VoiceEvent;
    if (typeof value.sessionId !== 'string' ||
        !['listening', 'processing', 'result', 'error', 'cancelled'].includes(value.status)) return;
    listener(value);
  });
  return () => subscription.remove();
}

export function voiceError(code: string | undefined): string {
  switch (code) {
    case 'permission': return 'Microphone access is off. Allow it in your phone’s app settings, then try again.';
    case 'no_match': return 'I could not hear the words clearly. Tap the microphone and try again.';
    case 'network': return 'Voice typing could not connect. Check your connection and try again.';
    case 'busy': return 'The microphone is busy. Wait a moment and try again.';
    case 'timeout': return 'Voice typing stopped after waiting. Your draft is still here.';
    case 'language': return 'This speech language is not available on your phone. Check its voice typing settings.';
    case 'unavailable': return 'Voice typing needs an enabled speech recognition service on this Android phone.';
    default: return 'Voice typing could not start. Your draft is still here. Try again.';
  }
}
