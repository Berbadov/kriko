/**
 * One switch for every haptic in the app.
 *
 * The calls are fire-and-forget and never throw: a phone without a vibration
 * motor, or a reader who turned haptics off, must not change what a press does.
 */

import * as Haptics from 'expo-haptics';

let enabled = true;

export function setHapticsEnabled(value: boolean): void {
  enabled = value;
}

export function hapticsEnabled(): boolean {
  return enabled;
}

/** A light tap for choosing a row, tab or option. */
export function tap(): void {
  if (enabled) Haptics.selectionAsync().catch(() => {});
}

/** A press acknowledgement for a real action. */
export function press(): void {
  if (enabled) Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => {});
}

/** A firmer acknowledgement for stopping or starting work. */
export function impact(): void {
  if (enabled) Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium).catch(() => {});
}

export function success(): void {
  if (enabled) Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => {});
}

export function warn(): void {
  if (enabled) Haptics.notificationAsync(Haptics.NotificationFeedbackType.Warning).catch(() => {});
}
