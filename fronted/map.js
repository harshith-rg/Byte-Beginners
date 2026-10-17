// =====================================
// AI SMART NAVIGATION
// GPS + DESTINATION + WALKING ROUTE
// =====================================

// Add your OpenRouteService API key below.
// Do not share your key with anyone.
const ORS_API_KEY = "eyJvcmciOiI1YjNjZTM1OTc4NTExMTAwMDFjZjYyNDgiLCJpZCI6IjExNDhhNzA1NjA4ODRmOWZiYjdkYmFhNDFkOGJkNGYwIiwiaCI6Im11cm11cjY0In0=";

// Create map
const map = L.map("map").setView([12.927963, 77.527165], 14);

L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19
}).addTo(map);

// HTML elements
const locationBtn = document.getElementById("locationBtn");
const gpsStatus = document.getElementById("gpsStatus");
const latitude = document.getElementById("latitude");
const longitude = document.getElementById("longitude");
const accuracy = document.getElementById("accuracy");

const destinationInput = document.getElementById("destination");
const searchBtn = document.getElementById("searchBtn");
const searchStatus = document.getElementById("searchStatus");

const routeBtn = document.getElementById("routeBtn");
const routeStatus = document.getElementById("routeStatus");
const routeSummary = document.getElementById("routeSummary");
const directions = document.getElementById("directions");

// State
let userMarker = null;
let destinationMarker = null;
let routeLayer = null;
let gpsWatchId = null;

// Coordinates for routing: [longitude, latitude]
let currentPosition = null;
let destinationPosition = null;

// =====================================
// GET GPS LOCATION
// =====================================

function startGPS() {
    if (!navigator.geolocation) {
        gpsStatus.textContent = "GPS is not supported by this browser.";
        return;
    }

    if (gpsWatchId !== null) {
        navigator.geolocation.clearWatch(gpsWatchId);
    }

    gpsWatchId = null;
    gpsStatus.textContent = "Getting your location...";

    gpsWatchId = navigator.geolocation.watchPosition(
        function (position) {
            const lat = position.coords.latitude;
            const lon = position.coords.longitude;
            const acc = position.coords.accuracy;

            latitude.textContent = lat.toFixed(6);
            longitude.textContent = lon.toFixed(6);
            accuracy.textContent = Math.round(acc) + " metres";

            currentPosition = [lon, lat];

            if (userMarker === null) {
                userMarker = L.marker([lat, lon])
                    .addTo(map)
                    .bindPopup("Your current location");

                map.setView([lat, lon], 16);
            } else {
                userMarker.setLatLng([lat, lon]);
            }

            gpsStatus.textContent =
                "Location detected. GPS accuracy: " +
                Math.round(acc) + " metres.";
        },
        function (error) {
            const messages = {
                1: "Location permission denied. Allow location access.",
                2: "Location unavailable. Try outdoors.",
                3: "GPS timed out. Please try again."
            };

            gpsStatus.textContent =
                messages[error.code] || "Unable to detect location.";

            gpsWatchId = null;
        },
        {
            enableHighAccuracy: true,
            maximumAge: 2000,
            timeout: 20000
        }
    );
}

locationBtn.addEventListener("click", startGPS);

// =====================================
// SEARCH DESTINATION
// =====================================

searchBtn.addEventListener("click", async function () {
    const query = destinationInput.value.trim();

    if (!query) {
        searchStatus.textContent = "Please enter a destination.";
        return;
    }

    searchBtn.disabled = true;
    searchStatus.textContent = "Searching for destination...";

    try {
        const url =
            "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&q=" +
            encodeURIComponent(query);

        const response = await fetch(url);

        if (!response.ok) {
            throw new Error("Destination search failed.");
        }

        const results = await response.json();

        if (results.length === 0) {
            destinationPosition = null;
            searchStatus.textContent =
                "Destination not found. Try another name.";
            return;
        }

        const place = results[0];
        const lat = Number(place.lat);
        const lon = Number(place.lon);

        destinationPosition = [lon, lat];

        if (destinationMarker) {
            map.removeLayer(destinationMarker);
        }

        destinationMarker = L.marker([lat, lon])
            .addTo(map)
            .bindPopup("Your destination");

        destinationMarker.openPopup();
        map.setView([lat, lon], 15);

        searchStatus.textContent =
            "Destination found: " + place.display_name;

        routeStatus.textContent =
            "Click Get Walking Route to calculate your route.";

        routeSummary.textContent = "";
        directions.replaceChildren();

        if (routeLayer) {
            map.removeLayer(routeLayer);
            routeLayer = null;
        }

    } catch (error) {
        searchStatus.textContent = "Search error: " + error.message;
    } finally {
        searchBtn.disabled = false;
    }
});

// =====================================
// GET WALKING ROUTE
// =====================================

routeBtn.addEventListener("click", async function () {
    if (!currentPosition) {
        routeStatus.textContent =
            "Waiting for GPS. Click Get My Location and allow permission.";
        startGPS();
        return;
    }

    if (!destinationPosition) {
        routeStatus.textContent =
            "Please search for a destination first.";
        return;
    }

    if (
        !ORS_API_KEY ||
        ORS_API_KEY === "PASTE_YOUR_API_KEY_HERE"
    ) {
        routeStatus.textContent =
            "Add your OpenRouteService API key at the top of map.js.";
        return;
    }

    routeBtn.disabled = true;
    routeStatus.textContent = "Calculating walking route...";
    routeSummary.textContent = "";
    directions.replaceChildren();

    try {
        const response = await fetch(
            "https://api.openrouteservice.org/v2/directions/foot-walking/geojson",
            {
                method: "POST",
                headers: {
                    "Authorization": ORS_API_KEY,
                    "Content-Type": "application/json",
                    "Accept": "application/geo+json, application/json"
                },
                body: JSON.stringify({
                    coordinates: [
                        currentPosition,
                        destinationPosition
                    ],
                    instructions: true,
                    language: "en"
                })
            }
        );

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(
                "Routing error " + response.status + ": " +
                errorText.slice(0, 200)
            );
        }

        const data = await response.json();

        if (!data.features || data.features.length === 0) {
            throw new Error("No walking route was returned.");
        }

        const feature = data.features[0];
        const properties = feature.properties;
        const summary = properties.summary;

        if (!summary) {
            throw new Error("Route details are missing.");
        }

        // Draw route on map
        if (routeLayer) {
            map.removeLayer(routeLayer);
        }

        routeLayer = L.geoJSON(feature, {
            style: {
                color: "#1769aa",
                weight: 6,
                opacity: 0.9
            }
        }).addTo(map);

        map.fitBounds(routeLayer.getBounds(), {
            padding: [25, 25]
        });

        // Show distance and estimated time
        const km = (summary.distance / 1000).toFixed(2);
        const minutes = Math.round(summary.duration / 60);

        routeSummary.textContent =
            "Walking distance: " + km +
            " km | Estimated time: " + minutes + " minutes";

        // Show turn-by-turn text directions
        const steps = (properties.segments || [])
            .flatMap(segment => segment.steps || []);

        if (steps.length === 0) {
            const item = document.createElement("li");
            item.textContent =
                "Route found. Follow the blue line on the map.";
            directions.appendChild(item);
        } else {
            steps.forEach(step => {
                const item = document.createElement("li");
                const metres = Math.round(step.distance || 0);

                item.textContent =
                    (step.instruction || "Continue along the route") +
                    (metres ? " — " + metres + " metres" : "");

                directions.appendChild(item);
            });
        }

        routeStatus.textContent = "Walking route found successfully!";

    } catch (error) {
        console.error("Walking route error:", error);
        routeStatus.textContent = error.message;
    } finally {
        routeBtn.disabled = false;
    }
});

// Start GPS
startGPS();