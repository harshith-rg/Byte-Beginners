import base64
import os
import requests
import cv2


def local_description(image, model):
    """Reuse the already-loaded detector for an offline description fallback."""
    result = model.predict(image, conf=0.40, imgsz=640, verbose=False)[0]
    if result.boxes is None or len(result.boxes) == 0:
        return (
            "I could not identify familiar objects in this frame. "
            "Please pause and use your usual mobility aid."
        )

    labels = []
    for box in result.boxes:
        label = result.names[int(box.cls.item())]
        if label not in labels:
            labels.append(label)

    return (
        "I can see: " + ", ".join(labels[:6]) +
        ". This description does not confirm safe walking space or exact distances."
    )


def describe_scene(image, question, model):
    """
    Optional adapter for a team-managed vision-language endpoint.
    Configure WATSONX_DESCRIBE_URL to an endpoint that accepts:
      {"image": "<base64 JPEG>", "question": "..."}
    and returns {"text": "..."}.
    This is a generic adapter, not a claim that raw watsonx.ai accepts this schema.
    """
    endpoint = os.getenv("WATSONX_DESCRIBE_URL")
    token = os.getenv("WATSONX_BEARER_TOKEN")

    if not endpoint or not token:
        return local_description(image, model), "local_fallback"

    ok, buffer = cv2.imencode(
        ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 75]
    )
    if not ok:
        raise RuntimeError("Could not encode image")

    payload = {
        "image": base64.b64encode(buffer).decode("ascii"),
        "question": question[:300],
    }
    response = requests.post(
        endpoint,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=8,
    )
    response.raise_for_status()
    text = response.json().get("text")

    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Description service returned no text")
    return text.strip()[:600], "remote_vision_service"
