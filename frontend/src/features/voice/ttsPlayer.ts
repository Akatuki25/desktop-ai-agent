/**
 * Plays WAV audio chunks received as binary WebSocket frames.
 *
 * Frame format from the daemon:
 *   byte 0      : tag (0x02 = TTS)
 *   bytes 1..8  : seq (BE u64) — increments per turn
 *   bytes 9..   : WAV payload
 *
 * The daemon now streams TTS one sentence per frame (issue #53), so a
 * single agent reply emits N frames in sequence. We schedule each new
 * chunk to start where the previous one ends, giving the user
 * gap-free playback even though chunks arrive at synthesis speed.
 *
 * Resets after a sufficiently long quiet period so a new turn starts
 * playback immediately.
 */

let audioCtx: AudioContext | null = null;
let nextStartTime = 0;
let lastSeq = -1;

function getAudioContext(): AudioContext {
  if (!audioCtx) {
    audioCtx = new AudioContext();
  }
  return audioCtx;
}

export async function playWav(wavBytes: ArrayBuffer, seq?: number): Promise<void> {
  const ctx = getAudioContext();
  const buffer = await ctx.decodeAudioData(wavBytes);

  // If this is the first chunk of a new turn (seq decreased or
  // playback queue has fully drained), start at "now".
  const now = ctx.currentTime;
  if (seq !== undefined && seq <= lastSeq) {
    nextStartTime = now;
  }
  if (nextStartTime < now) {
    nextStartTime = now;
  }

  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.start(nextStartTime);
  nextStartTime += buffer.duration;
  if (seq !== undefined) lastSeq = seq;
}
