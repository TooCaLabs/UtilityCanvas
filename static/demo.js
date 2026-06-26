const textInput = document.getElementById("text-input");
const charCount = document.getElementById("char-count");
const generateBtn = document.getElementById("generate-btn");
const statusEl = document.getElementById("status");
const loader = document.getElementById("loader");
const result = document.getElementById("result");
const audioPlayer = document.getElementById("audio-player");

const DEMO_LIMIT = Number(window.DEMO_LIMIT || 200);
const DEMO_API_URL = window.DEMO_API_URL || "/api/demo-speak";

function setStatus(message, kind = "idle") {
  statusEl.className = `status ${kind}`;
  statusEl.textContent = message;
}

function setLoading(isLoading) {
  generateBtn.disabled = isLoading;
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
    setStatus(`Demo limit is ${DEMO_LIMIT} characters.`, "error");
  } else {
    setStatus("Ready.", "idle");
  }
});

generateBtn.addEventListener("click", async () => {
  const text = textInput.value.trim();
  const { tooLong } = updateState();

  if (!text) {
    setStatus("Enter text first.", "error");
    textInput.focus();
    return;
  }

  if (tooLong) {
    setStatus(`Keep text under ${DEMO_LIMIT} characters.`, "error");
    return;
  }

  setLoading(true);
  setStatus("Generating demo audio...", "loading");

  try {
    const response = await fetch(DEMO_API_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Unable to generate demo audio.");
    }

    audioPlayer.src = `${data.audio_url}?t=${Date.now()}`;
    result.classList.remove("hidden");
    setStatus("Done. Demo audio is ready.", "success");
  } catch (error) {
    setStatus(error.message || "Demo request failed.", "error");
  } finally {
    setLoading(false);
  }
});

updateState();
