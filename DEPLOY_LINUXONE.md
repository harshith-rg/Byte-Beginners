# Deploy PathVoice on IBM LinuxONE

This guide describes deploying this project to Ubuntu 22.04 on IBM LinuxONE
(`s390x`) with Python 3.10. It is a set of instructions for you to run; no
connection to the VM or deployment action has been performed.

## 1. Understand what must run

The application has one FastAPI process:

- `backend/main.py` serves the web page, `/health`, and the `/ws` WebSocket.
- `frontend/index.html`, `frontend/app.js`, and `frontend/style.css` are served
  by that same process. The browser connects to `/ws` on the page's own host,
  using `wss:` when the page is HTTPS.
- By default, `backend/main.py` imports OpenCV, NumPy, FastAPI, and Ultralytics
  and loads `yolo11n.pt` as the module starts, before `/health` can answer.
- The experimental OpenCV DNN engine avoids importing PyTorch, TorchVision,
  and Ultralytics, but still requires a usable OpenCV `cv2` module and NumPy.
  It is opt-in only; the default remains Ultralytics.
- The inspected backend does not read environment variables. The values shown
  as comments in `.env.example` are placeholders for integrations that are
  not implemented yet.

The app therefore needs these project files in the matching directory layout:

```text
pathvoice/
  backend/
    main.py
    requirements.txt
    yolo11n.pt       # default Ultralytics mode
    yolo11n.onnx     # optional, exported for ONNX mode
  frontend/
    index.html
    app.js
    style.css
```

`backend/bus.jpg` is used by the ONNX sample-inference integration test. The
`.pt` model file is needed by the existing Ultralytics implementation and is
excluded from Git by the project's `.gitignore`; a Git clone will not include
it unless you transfer it separately.

## 2. Choose and preflight an inference engine

### Default: Ultralytics `.pt` engine

The default engine is the existing Ultralytics implementation. It requires
OpenCV, NumPy, Ultralytics, PyTorch, TorchVision, the `yolo11n.pt` model, and
working compatible versions of those packages. A successful PyTorch import
alone does not validate TorchVision or YOLO. Use this mode only if the complete
stack has already been verified on the target; do not install an arbitrary
TorchVision version to satisfy a broad dependency minimum.

### Opt-in: OpenCV DNN ONNX engine

This experimental path is intended to use the Ubuntu OpenCV DNN CPU backend
and a YOLO11n COCO ONNX export. It does not use PyTorch, TorchVision, or
Ultralytics at server runtime. It requires:

- OpenCV with `cv2.dnn` and NumPy importable by the selected Python process.
- An exported YOLO11 COCO ONNX model using a 640-by-640 input and raw output
  with four box channels plus 80 class-score channels.
- Real validation on the target using `backend/bus.jpg`.

The repository contains only `backend/yolo11n.pt`, not `yolo11n.onnx`. The
parser handles the common raw YOLO11 COCO output layouts `[1, 84, N]` and
`[1, N, 84]`, uses letterboxed RGB input and per-class OpenCV NMS, and returns
the existing normalized detection shape. Synthetic unit tests cover these
assumptions; they do not prove that a particular export has that output or that
OpenCV 4.5.4 can execute it. A model that exports different output channels or
semantics will fail explicitly or must be separately validated before use.

Export only in a Python environment where the existing Ultralytics/PyTorch
export stack is known to work. Python 3.14.6 or a teammate's Python 3.15 is not
automatically compatible. For an already verified export environment, the
export command is:

```bash
cd backend
python -c "from ultralytics import YOLO; YOLO('yolo11n.pt').export(format='onnx', imgsz=640)"
```

The expected output is `backend/yolo11n.onnx`. Confirm that file exists, then
transfer it through the same approved source-transfer method as the project.
Do not install exporter dependencies merely to try this command without first
checking their Python and platform compatibility.

The separate [requirements-linuxone.txt](./backend/requirements-linuxone.txt)
deliberately omits pip OpenCV, NumPy, Ultralytics, PyTorch, and TorchVision.
It assumes Ubuntu's `python3-opencv` and its system NumPy dependency are already
installed and importable by the selected Python process. The VM's existing
virtual environment was reported to have `include-system-site-packages = false`;
in that configuration APT-installed `cv2` and NumPy are not automatically
visible. Test visibility before starting:

```bash
PYTHONPATH=/usr/lib/python3/dist-packages /home/linux1/pathvoice/.venv/bin/python -c "import sys, cv2, numpy; print('cv2:', cv2.__version__, cv2.__file__); print('numpy:', numpy.__version__, numpy.__file__); print('Python:', sys.executable)"
```

This is an import/path check, not an installation command. It intentionally
shows which OpenCV and NumPy files Python loads. If it fails or loads an
unexpected NumPy/OpenCV combination, stop; do not assume system OpenCV can
safely be mixed with the virtual environment. The `PYTHONPATH` setting places
Ubuntu's system modules ahead of the venv's modules for that process, so check
the printed paths carefully. Do not edit the existing venv configuration as
part of this guide.

## 3. Transfer the project safely

The earlier SCP attempt failed with `Permission denied (publickey)`. That means
the SSH server did not accept the offered public-key authentication. Do not
send anyone your private key, and do not assume the VM has registered the
matching public key.

### Option A: SCP after public-key access is fixed

On Windows PowerShell, you can display the fingerprint of the **public** key
file without reading or printing the private key:

```powershell
ssh-keygen -lf "$env:USERPROFILE\.ssh\id_ed25519.pub"
```

Ask the VM administrator, or someone who already has authorized access, to
compare that fingerprint with the public keys registered for the `linux1`
account. On the VM, an authorized administrator can list fingerprints from
`~/.ssh/authorized_keys` with:

```bash
ssh-keygen -lf ~/.ssh/authorized_keys
```

Compare fingerprints, not private-key contents. If your public key is not
registered, ask the administrator to install the public key through the
approved process. Do not change SSH server configuration yourself.

Once the administrator confirms the correct public key is authorized, test
interactive access from PowerShell:

```powershell
ssh -i "$env:USERPROFILE\.ssh\id_ed25519" linux1@148.100.108.215
```

After SSH works, run SCP from the project root in a separate PowerShell
session:

```powershell
scp -i "$env:USERPROFILE\.ssh\id_ed25519" -r .\backend .\frontend linux1@148.100.108.215:~/pathvoice/
```

This transfers the backend directory, including `yolo11n.pt`, and the frontend.
The VM account must have write permission to `~/pathvoice`. If SSH still reports
`Permission denied (publickey)`, stop and ask the administrator to verify the
account name, registered public key, and SSH access policy.

### Option B: Clone a private Git repository

If Git is available on both computers and the VM is allowed to access your
private repository, you can clone the source there using the repository's
approved authentication method. Do not put an access token or password in the
repository URL, source code, or a committed file. The `.pt` model is ignored by
Git, so transfer `backend/yolo11n.pt` separately through an approved private
transfer method. Confirm that it is present at `~/pathvoice/backend/yolo11n.pt`
before attempting startup.

## 4. Start the app for a local VM check

The paths in `main.py` are relative to the current directory. Start Uvicorn
from `~/pathvoice/backend`, not from the project root:

```bash
cd /home/linux1/pathvoice/backend
PATHVOICE_INFERENCE_ENGINE=onnx \
PATHVOICE_ONNX_MODEL=/home/linux1/pathvoice/backend/yolo11n.onnx \
PYTHONPATH=/usr/lib/python3/dist-packages \
/home/linux1/pathvoice/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
```

This explicitly selects the ONNX engine for this process; without
`PATHVOICE_INFERENCE_ENGINE=onnx`, the backend continues to use Ultralytics
and `yolo11n.pt`.

This binds the application to the VM itself, which is appropriate when a
reverse proxy is configured in front of it. Do not expose port 8000 directly
to the public internet. Keep this foreground process running while testing.

In a second SSH session on the VM, check the health endpoint:

```bash
curl -i http://127.0.0.1:8000/health
```

When startup succeeds, expect HTTP 200 and a JSON response similar to:

```json
{"status":"ok","service":"smart-navigation-backend"}
```

If Uvicorn fails before serving requests, check the console output. Common
causes include an unavailable Python dependency, a missing model file, or
starting from the wrong working directory.

## 5. Keep the app running with systemd

After the foreground test succeeds, stop that Uvicorn process with `Ctrl+C`.
You can then run it as a service so it starts again after a VM reboot. The
example below assumes the home directory is `/home/linux1`; check with
`echo "$HOME"` and replace that path if yours differs.

Create a service file:

```bash
sudo nano /etc/systemd/system/pathvoice.service
```

Enter:

```ini
[Unit]
Description=PathVoice FastAPI application
After=network.target

[Service]
User=linux1
WorkingDirectory=/home/linux1/pathvoice/backend
ExecStart=/home/linux1/pathvoice/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Environment=PATHVOICE_INFERENCE_ENGINE=onnx
Environment=PATHVOICE_ONNX_MODEL=/home/linux1/pathvoice/backend/yolo11n.onnx
Environment=PYTHONPATH=/usr/lib/python3/dist-packages
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Save and exit, then enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pathvoice
sudo systemctl status pathvoice --no-pager
```

If it fails, inspect its logs with:

```bash
sudo journalctl -u pathvoice -n 100 --no-pager
```

## 6. Make the page available over HTTPS

For a browser on your phone to use the camera and location, the page must be
served over HTTPS. Plain HTTP is suitable only for a browser on the same
machine using `localhost`; a remote phone needs HTTPS. The existing frontend
automatically uses a secure WebSocket (`wss:`) when loaded over HTTPS, so the
proxy must forward WebSocket upgrade requests.

One typical arrangement is Nginx in front of Uvicorn:

1. Point a domain name you control to the VM's public IP.
2. Allow inbound ports 80 and 443 in the cloud firewall/security group and
   host firewall as appropriate. Keep port 8000 private.
3. Install Nginx:

   ```bash
   sudo apt update
   sudo apt install -y nginx
   ```

4. Create `/etc/nginx/sites-available/pathvoice` and replace
   `your-domain.example` with your domain:

   ```nginx
   server {
       listen 80;
       server_name your-domain.example;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_http_version 1.1;
           proxy_set_header Host $host;
           proxy_set_header Upgrade $http_upgrade;
           proxy_set_header Connection "upgrade";
           proxy_read_timeout 3600;
       }
   }
   ```

   Enable and check the Nginx site:

   ```bash
   sudo ln -s /etc/nginx/sites-available/pathvoice /etc/nginx/sites-enabled/pathvoice
   sudo nginx -t
   sudo systemctl reload nginx
   ```

5. Obtain and configure a TLS certificate. A public certificate authority
   normally requires a domain name that resolves to the VM:

   ```bash
   sudo apt install -y certbot python3-certbot-nginx
   sudo certbot --nginx -d your-domain.example
   ```

6. After HTTPS is active, open `https://your-domain.example/` on the phone.
   Replace the sample hostname with your configured domain.

If you do not have a domain, ask your administrator which approved HTTPS
tunnel or certificate option is available. Do not enter camera credentials
or send camera frames over an untrusted public endpoint.

## 7. Validate the health endpoint and web UI

After the app is running:

1. On the VM, run `curl -i http://127.0.0.1:8000/health` and confirm HTTP 200
   with `"status":"ok"`.
2. From your computer, open `https://your-domain.example/`. Confirm the
   PathVoice page and stylesheet load.
3. Open browser developer tools and check that the page can establish its
   `/ws` WebSocket connection. HTTPS pages should connect with `wss:`.
4. On a supported phone browser, open the same HTTPS page, grant camera
   permission, and tap **Start camera and alerts**. Confirm the connection
   badge changes to Connected and the frame count increases.
5. If the UI loads but camera startup fails, check HTTPS, browser permissions,
   and the WebSocket proxy configuration. If the page does not load, check the
   reverse proxy and firewall before changing application code.

For actual model validation, from `~/pathvoice/backend` run:

```bash
PATHVOICE_INFERENCE_ENGINE=onnx \
PATHVOICE_ONNX_MODEL=/home/linux1/pathvoice/backend/yolo11n.onnx \
PYTHONPATH=/usr/lib/python3/dist-packages \
/home/linux1/pathvoice/.venv/bin/python -m unittest discover -s tests -v
```

The ONNX sample-image integration test must run (not skip) and detect objects
from `backend/bus.jpg`. It skips when OpenCV, NumPy, or the ONNX file is absent.
Also test the live HTTPS page with a phone camera and confirm a WebSocket frame
response and visible/spoken detections. A passing synthetic parser test or
`/health` response alone is not a real inference verification.

The health endpoint confirms the service started; it does not prove object
detection is accurate, safe, or suitable as a mobility aid. Do not use this
prototype as a sole mobility aid.

## 8. If YOLO cannot run on LinuxONE

The current application does not call a separate inference service. If OpenCV
DNN cannot run the ONNX model on LinuxONE and no compatible local inference
stack is available, a possible future design is:

1. Keep the FastAPI frontend/API process on LinuxONE, where it receives the
   browser's frames and handles the UI protocol.
2. Change its detector integration to send each frame to an inference API
   running on a host where the required model stack is supported.
3. Have that service return detections in the existing normalized response
   shape (`label`, `class_name`, `confidence`, `box`, and `level`).

That design requires implementation and end-to-end testing; it is not present
in this repository today. Keep the inference endpoint on a private network or
behind a restrictive firewall, use HTTPS/TLS and service authentication,
restrict which hosts can call it, set request size and timeout limits, and
decide how frames are protected and retained. Camera frames can contain
sensitive personal information.
