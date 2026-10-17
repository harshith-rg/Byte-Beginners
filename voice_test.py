import pyttsx3

engine = pyttsx3.init()

engine.setProperty("rate", 160)
engine.setProperty("volume", 1.0)

engine.say("Hello! AI navigation assistant is ready.")
engine.say("Person detected ahead.")
engine.say("Car detected ahead.")

engine.runAndWait()