const textInput = document.getElementById("text-input");
const voiceSelect = document.getElementById("voice-select");
const rateInput = document.getElementById("rate-input");
const rateValue = document.getElementById("rate-value");
const charCount = document.getElementById("char-count");
const generateBtn = document.getElementById("generate-btn");
const clearBtn = document.getElementById("clear-btn");
const sampleBtn = document.getElementById("sample-btn");
const statusEl = document.getElementById("status");
const loader = document.getElementById("loader");
const result = document.getElementById("result");
const audioPlayer = document.getElementById("audio-player");
const downloadLink = document.getElementById("download-link");

const DEMO_LIMIT = Number(window.DEMO_LIMIT || 280);
const SAMPLE_TEXT = "This short demo gives you a preview before downloading the full desktop app.";

function setStatus(message, kind = "idle") {
  statusEl.className = `status ${kind}`;
  statusEl.textContent = message;
}

function setLoading(isLoading) {
  generateBtn.disabled = isLoading;
  clearBtn.disabled = isLoading;
  sampleBtn.disabled = isLoading;
  rateInput.disabled = isLoading;
  voiceSelect.disabled = isLoading || voiceSelect.options.length === 0;
  loader.classList.toggle("hidden", !isLoading);
}

function updateState() {
  const count = textInput.value.trim().length;
  const tooLong = count > DEMO_LIMIT;
  charCount.textContent = `${count} / ${DEMO_LIMIT}`;
  charCount.classList.toggle("over", tooLong);
  generateBtn.disabled = tooLong || count === 0;
  return { count, tooLong };
}

textInput.addEventListener("input", () => {
  const { tooLong } = updateState();
  if (tooLong) {
    setStatus(`Demo is limited to ${DEMO_LIMIT} characters.`, "error");
  } else {
    setStatus("Ready.", "idle");
  }
});

rateInput.addEventListener("input", () => {
  rateValue.textContent = rateInput.value;
});

sampleBtn.addEventListener("click", () => {
  textInput.value = SAMPLE_TEXT;
  updateState();
  setStatus("Sample inserted.", "idle");
  textInput.focus();
});

clearBtn.addEventListener("click", () => {
  textInput.value = "";
  updateState();
  result.classList.add("hidden");
  audioPlayer.pause();
  audioPlayer.removeAttribute("src");
  audioPlayer.load();
  setStatus("Cleared.", "idle");
});

generateBtn.addEventListener("click", async () => {
  const text = textInput.value.trim();
  const { tooLong } = updateState();

  if (!text) {
    setStatus("Add text first.", "error");
    textInput.focus();
    return;
  }

  if (tooLong) {
    setStatus(`Keep text at ${DEMO_LIMIT} characters or less.`, "error");
    return;
  }

  setLoading(true);
  setStatus("Generating demo audio...", "loading");

  try {
    const response = await fetch("/api/demo-speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
        voice: voiceSelect.value,
        rate: Number(rateInput.value),
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Unable to generate demo audio.");
    }

    const fileUrl = `${data.audio_url}?t=${Date.now()}`;
    audioPlayer.src = fileUrl;
    downloadLink.href = fileUrl;
    downloadLink.download = `demo_${Date.now()}.wav`;
    result.classList.remove("hidden");

    setStatus(`Done. ${data.characters} chars with ${data.voice}.`, "success");
  } catch (error) {
    setStatus(error.message || "Demo request failed.", "error");
  } finally {
    setLoading(false);
  }
});

updateState();
