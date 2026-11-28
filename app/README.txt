VIP: Virtual Interview Patient (Windows)
=======================================

Practise history-taking with a virtual patient: you speak, the patient answers in character
with a voice and a face, and reveals facts only when you ask the right questions.

START
  1. Unzip this folder anywhere (a short path such as C:\VIP is best).
  2. Double-click "Start VIP Patient.exe".
     Windows may warn that the app is from an unknown publisher: More info > Run anyway.
  3. The VIP Patient window opens. When an interview starts, the patient fills it and
     your timer and notes float on top. On first start it asks for your own OpenAI and
     ElevenLabs API keys (see below).
     Then choose "I'm a student", enter your name, pick a patient, start the interview, click
     "Start talking" and greet the patient (the app uses your microphone).
  Close the window to stop everything. F11 switches to full screen.

YOUR KEYS
  - OpenAI API key: platform.openai.com > API keys. The account needs a little prepaid credit.
  - ElevenLabs API key: elevenlabs.io > Developers > API keys. A free account works for a short
    session; give the key access to Agents, Text to Speech, Speech to Text and the User read
    permission.
  The keys are stored encrypted on this computer only (for your Windows user) and are sent only
  to OpenAI and ElevenLabs. To make the voice work, the app stores your OpenAI key as a secret in
  your ElevenLabs workspace and creates one agent there named "VIP Patient (local app)". You can
  delete both in ElevenLabs afterwards; "API KEYS" > "Forget keys" in the app removes the
  local copy.

NEEDS
  Windows 10 or 11 (64-bit), a recent graphics card (the face is rendered in real time),
  8 GB of memory or more, the Microsoft Edge WebView2 Runtime (part of Windows 11), a microphone (a headset works best) and an internet connection.

IF SOMETHING GOES WRONG
  - "port ... already in use": another program uses it; close that program and start again.
  - "Waiting for the patient..." stays: the patient did not start; the interview still works.
  - Logs: %LOCALAPPDATA%\VIPPatient\logs

This folder contains Unreal Engine and MetaHuman content by Epic Games. It is shared privately
for evaluation; please do not redistribute it.
