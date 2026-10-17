import pyttsx3
import time

def speak(message):
    engine = pyttsx3.init("sapi5")
    engine.setProperty("volume", 1.0)
    engine.say(message)
    engine.runAndWait()
    engine.stop()
    time.sleep(1)

speak("Person detected")
speak("Car detected")
speak("Handbag detected")

print("Test completed")