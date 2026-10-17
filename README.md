# SightPath

### See the path. Hear what matters.

SightPath is a mobile-first assistive navigation prototype that turns a smartphone camera into a voice-guided companion. It detects familiar objects, describes where they appear in the camera view, and can provide spoken walking directions to a chosen destination.

> **A prototype for exploration and demonstration.** SightPath can miss objects or estimate distance incorrectly. It is not a certified mobility aid and must not replace a white cane, guide dog, or other trusted mobility support. Test only with a sighted companion.

---

## The idea

A phone already has a camera, GPS, speaker, and vibration motor. SightPath brings those capabilities together in a browser-based experience, with no separate hardware or app-store installation required.

The project explores two kinds of guidance:

- **Obstacle awareness:** Detect selected everyday objects and speak a concise alert about their approximate position.
- **Walking navigation:** Search for a destination, request a walking route, and announce upcoming turns as GPS updates arrive.

## What it can do

### Camera and obstacle alerts

- Runs object detection in the browser with TensorFlow.js and COCO-SSD.
- Draws detection boxes and labels over the live camera image.
- Groups object position into left, ahead, or right.
- Estimates rough proximity from the height of a detected object in the image.
- Speaks selected alerts and uses vibration where the device supports it.
- Applies alert thresholds and cooldowns to reduce repeated announcements.

### Destination and walking guidance

- Searches for destinations with OpenStreetMap Nominatim.
- Requests walking routes from the public OSRM foot-routing service.
- Uses device geolocation to track progress toward the next route instruction.
- Announces upcoming turns and can request a new route after sustained off-route readings.
- Includes a compass indicator on supported devices and browsers.

### Voice interaction

- Supports speech recognition in compatible browsers.
- Accepts commands such as “navigate to…”, “start”, “stop”, and “repeat”.
- Uses browser speech synthesis for spoken feedback.

## How it works

    Phone browser
    ├── Camera → TensorFlow.js / COCO-SSD → detections and overlay
    ├── Detection boxes → direction and approximate proximity → voice / vibration
    ├── Destination text → Nominatim place search
    ├── GPS position + destination → OSRM walking route → turn guidance
    └── Device orientation → compass indicator

Object detection and alert logic run in the browser. Place search and routing use online OpenStreetMap-related services. Camera, GPS, speech, vibration, and compass capabilities depend on the device and browser.

## Built with

- **TypeScript** and **Vite**
- **TensorFlow.js** and **COCO-SSD** for browser-based object detection
- **Web APIs** for camera, geolocation, speech synthesis, speech recognition, vibration, and device orientation
- **OpenStreetMap Nominatim** for place search
- **OSRM foot routing** for walking directions

## Get started

### Requirements

- Node.js and npm
- A modern browser
- A camera and location-enabled device for the full experience
- Internet access for model loading, destination search, and route requests

Camera and location access generally require a secure context. Localhost is usually permitted for development; phone or hosted testing should use HTTPS.

### Install and run

Clone the repository, then run these commands from the folder containing package.json:

    git clone <your-repository-url>
    cd <repository-folder>
    npm install
    npm run dev

Open the local URL printed by Vite and grant the requested camera and location permissions.

To create a production build:

    npm run build

## Try it

1. Open SightPath in a supported browser.
2. Tap **Start camera** and allow camera access.
3. Enter a destination and tap **Get route**.
4. Tap **Start guidance** and allow location access.
5. Try the voice input button if speech recognition is available.

For reliable GPS testing, go outdoors and use a short, familiar route. Browser support differs, so test on the same phone and browser you plan to demonstrate.

## Code map

    src/
    ├── main.ts       Camera, object detection, overlays, proximity, and alerts
    ├── nav.ts        Destination search, walking route, GPS progress, and rerouting
    ├── compass.ts    Device heading and compass indicator
    ├── voice.ts      Speech recognition and navigation commands
    ├── style.css     Application styles
    └── assets/       Images and static assets

## Important limitations

- **Proximity is an estimate.** It is inferred from detection-box size and assumed object dimensions; the app does not measure true depth.
- **Detection is imperfect.** Results can change with lighting, camera angle, distance, motion, and device performance.
- **GPS has uncertainty.** Indoor readings and readings near tall buildings can be inaccurate, which can affect turn announcements and rerouting.
- **Browser support varies.** Camera, speech recognition, speech synthesis, vibration, and compass behavior differ across devices. Some devices require a user tap to enable speech or motion access.
- **Online services are dependencies.** Model loading, place search, and routing may fail without internet access or when public services are unavailable.
- **No SOS feature is implemented in this version.**

## Responsible use

SightPath is an educational prototype. Do not rely on it to cross roads, avoid hazards, or travel independently. During development and demonstrations, use a sighted companion, keep to a safe area, and follow established mobility practices.

## Contributing

Contributions and improvements are welcome.

1. Create a branch for your change.
2. Keep pull requests focused and explain what changed.
3. Do not commit API credentials, private location data, or camera captures.
4. Run the production build before opening a pull request:

       npm run build

## Roadmap ideas

- Add a map view with the current position, destination, and route
- Add a user-controlled SOS message flow
- Improve and test compass guidance on more devices
- Add stronger GPS filtering and more robust route-progress checks
- Evaluate performance and accessibility with users and assistive-technology specialists

## License

No license is included yet. Add a LICENSE file to the repository before granting others permission to reuse or redistribute the code.
