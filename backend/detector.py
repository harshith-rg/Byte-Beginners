from ultralytics import YOLO

print("Loading AI model...")

model = YOLO("yolov8n.pt")

print("Detecting objects...")

results = model.predict(
    source="bus.jpg",
    save=True,
    conf=0.4
)

print("Detection completed!")
print("Check the runs/detect folder for the result.")