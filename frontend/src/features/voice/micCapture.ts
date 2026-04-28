/**
 * Microphone capture for push-to-talk STT.
 *
 * Pipeline: getUserMedia → AudioContext (16 kHz) → ScriptProcessorNode
 * (4096) → Float32→Int16 → tagged binary frame → caller's send().
 *
 * Frame layout matches shared/rpc/schema.json:
 *   byte 0      : tag 0x01 (mic PCM)
 *   bytes 1..8  : seq (LE u64) — increments per frame within a session
 *   bytes 9..   : PCM payload (linear16 mono 16 kHz)
 *
 * ScriptProcessorNode is deprecated in favor of AudioWorklet, but
 * AudioWorklet requires shipping a separate worker file which the
 * Tauri build doesn't currently set up. ScriptProcessor still works
 * in Chromium-based WebViews; revisit when we need lower latency.
 */

type SendBinary = (data: ArrayBuffer) => void;

let stream: MediaStream | null = null;
let audioCtx: AudioContext | null = null;
let processor: ScriptProcessorNode | null = null;
let source: MediaStreamAudioSourceNode | null = null;
let seq = 0n;

function floatToInt16(float32: Float32Array): Int16Array {
  const out = new Int16Array(float32.length);
  for (let i = 0; i < float32.length; i++) {
    let s = float32[i];
    if (s > 1) s = 1;
    if (s < -1) s = -1;
    out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }
  return out;
}

function frame(pcm: Int16Array): ArrayBuffer {
  const buf = new ArrayBuffer(9 + pcm.byteLength);
  const view = new DataView(buf);
  view.setUint8(0, 0x01); // mic tag
  view.setBigUint64(1, seq, true); // LE u64 per schema
  seq += 1n;
  new Uint8Array(buf, 9).set(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength));
  return buf;
}

export async function startCapture(send: SendBinary): Promise<void> {
  if (stream) return; // already running

  seq = 0n;
  stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      sampleRate: 16000,
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
    },
    video: false,
  });

  // sampleRate on the constraints is a hint; the AudioContext rate is
  // what actually drives ScriptProcessor output. Force 16 kHz so we
  // match what Deepgram's URL declares.
  audioCtx = new AudioContext({ sampleRate: 16000 });
  source = audioCtx.createMediaStreamSource(stream);
  processor = audioCtx.createScriptProcessor(4096, 1, 1);

  processor.onaudioprocess = (ev) => {
    const input = ev.inputBuffer.getChannelData(0);
    const pcm = floatToInt16(input);
    send(frame(pcm));
  };

  source.connect(processor);
  // ScriptProcessor only fires onaudioprocess if connected to a sink
  // somewhere in the graph; route through destination but mute by not
  // generating output (it reads from input buffer, not output).
  processor.connect(audioCtx.destination);
}

export async function stopCapture(): Promise<void> {
  if (processor) {
    processor.disconnect();
    processor.onaudioprocess = null;
    processor = null;
  }
  if (source) {
    source.disconnect();
    source = null;
  }
  if (stream) {
    stream.getTracks().forEach((t) => t.stop());
    stream = null;
  }
  if (audioCtx) {
    try {
      await audioCtx.close();
    } catch {
      // ignore
    }
    audioCtx = null;
  }
}

export function isCapturing(): boolean {
  return stream !== null;
}
