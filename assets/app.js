let mediaRecorder = null;
let audioChunks = [];
let isRecording = false;
let audioStream = null;
let currentAudio = null;

const micBtn = document.getElementById('mic-btn');
const questionBubble = document.getElementById('question-bubble');
const questionText = document.getElementById('question-text');
const hintText = document.querySelector('.hint-text');

micBtn.addEventListener('click', () => {
  if (isRecording) {
    stopRecording();
  } else {
    startRecording();
  }
});

async function startRecording() {
  try {
    audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mimeType = MediaRecorder.isTypeSupported('audio/webm')
      ? 'audio/webm'
      : 'audio/ogg';
    mediaRecorder = new MediaRecorder(audioStream, mimeType ? { mimeType } : {});
    audioChunks = [];

    mediaRecorder.ondataavailable = (event) => {
      audioChunks.push(event.data);
    };

    mediaRecorder.onstop = () => {
      if (audioStream) {
        audioStream.getTracks().forEach(track => track.stop());
        audioStream = null;
      }
      sendAudio();
    };

    mediaRecorder.start();
    isRecording = true;
    micBtn.classList.add('recording');
    micBtn.disabled = false;
    hintText.textContent = 'Tap to stop speaking';
    questionBubble.classList.add('hidden');
  } catch (err) {
    console.error('Error accessing microphone:', err);
    hintText.textContent = 'Microphone access denied';
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();
  }
  isRecording = false;
  micBtn.classList.remove('recording');
  micBtn.disabled = true;
  hintText.textContent = 'Processing...';
}

async function sendAudio() {
  const audioBlob = new Blob(audioChunks, { type: mediaRecorder.mimeType || 'audio/webm' });
  const formData = new FormData();
  formData.append('audio', audioBlob, 'recording.' + (mediaRecorder.mimeType.includes('webm') ? 'webm' : 'ogg'));

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      body: formData
    });

    const data = await response.json();

    if (data.error) {
      hintText.textContent = data.error;
      micBtn.disabled = false;
      return;
    }

    questionText.textContent = data.question;
    questionBubble.classList.remove('hidden');

    playAudio(data.audio);
  } catch (err) {
    console.error('Error sending audio:', err);
    hintText.textContent = 'Connection error';
    micBtn.disabled = false;
  }
}

function playAudio(base64Data) {
  const binaryStr = atob(base64Data);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }
  const blob = new Blob([bytes], { type: 'audio/mpeg' });
  const url = URL.createObjectURL(blob);

  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }

  currentAudio = new Audio(url);
  currentAudio.onended = () => {
    micBtn.disabled = false;
    hintText.textContent = 'Tap to start speaking';
    URL.revokeObjectURL(url);
  };
  currentAudio.onerror = () => {
    micBtn.disabled = false;
    hintText.textContent = 'Tap to start speaking';
    URL.revokeObjectURL(url);
  };
  currentAudio.play();
}
