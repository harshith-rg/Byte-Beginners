from ultralytics import YOLO

print("Loading AI model...")

model = YOLO("yolov8n.pt")

print("Detecting objects...")

results = model(
    "https://ultralytics.com/images/bus.jpg",
    save=True
)

print("Detection completed!")
print("Check the runs/detect folder for the result.")
