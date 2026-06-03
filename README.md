# Setup

Basic setup to get this running:

**Before first run, to setup venv & install dependencies**
```
python -m venv venv
pip install -r requirements  // Win11 Store installs may want "py -m pip install -r requirements"
```

**Whenever you start a new session**
```
. venv/Scripts/Activate  // windows, on unix: . venv/bin/activate
python calib_client.py
```
