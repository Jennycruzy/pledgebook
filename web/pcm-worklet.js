class PledgebookPCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.inputRate = sampleRate;
    this.position = 0;
    this.buffer = [];
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
    if (output.length) { const pcm = new Int16Array(output); this.port.postMessage(pcm.buffer, [pcm.buffer]); }
    return true;
  }
}
registerProcessor('pledgebook-pcm', PledgebookPCMProcessor);
