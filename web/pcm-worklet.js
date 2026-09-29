class PledgebookPCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.inputRate = sampleRate;
    this.position = 0;
    this.buffer = [];
    this.pending = [];
  }
  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;
    for (const sample of input) this.buffer.push(sample);
    const step = this.inputRate / 16000;
    const output = [];
    while (this.position < this.buffer.length) {
      const sample = this.buffer[Math.floor(this.position)];
      output.push(Math.max(-32768, Math.min(32767, Math.round(sample * 32767))));
      this.position += step;
    }
    const consumed = Math.floor(this.position);
    if (consumed > 0) { this.buffer = this.buffer.slice(consumed); this.position -= consumed; }
    this.pending.push(...output);
    // AssemblyAI Realtime expects useful audio frames rather than the tiny
    // 128-sample render quanta produced by the browser. Send 100 ms of 16 kHz
    // PCM per message, matching the proven server-side WAV streaming path.
    while (this.pending.length >= 1600) {
      const pcm = new Int16Array(this.pending.splice(0, 1600));
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}
registerProcessor('pledgebook-pcm', PledgebookPCMProcessor);
