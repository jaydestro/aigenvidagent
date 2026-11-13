import os,sys,time
import azure.cognitiveservices.speech as sp
cfg=sp.SpeechConfig(subscription=os.environ["SPK"],region="eastus2"); cfg.speech_recognition_language="en-US"
r=sp.SpeechRecognizer(speech_config=cfg,audio_config=sp.audio.AudioConfig(filename=sys.argv[1]))
out=[];done=[False]
r.recognized.connect(lambda e: out.append(e.result.text))
r.session_stopped.connect(lambda e: done.__setitem__(0,True)); r.canceled.connect(lambda e: done.__setitem__(0,True))
r.start_continuous_recognition()
while not done[0]: time.sleep(0.3)
r.stop_continuous_recognition(); print(" ".join(out))
