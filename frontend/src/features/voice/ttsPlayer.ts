/**
 * Plays WAV audio received as binary WebSocket frames.
 *
 * The daemon sends TTS frames with tag byte 0x02, 8-byte seq, then
 * raw WAV payload. This module decodes the WAV and plays it through
 * the Web Audio API.
 */

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext {
  if (!audioCtx) {
    audioCtx = new AudioContext();
  }
  return audioCtx;
}

export async function playWav(wavBytes: ArrayBuffer): Promise<void> {
  const ctx = getAudioContext();
  const buffer = await ctx.decodeAudioData(wavBytes);
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.start(0);
}
