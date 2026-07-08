# Installing map2arcpy — the simple version

New to this? Read this page top to bottom. It assumes you know nothing about
git or Python packaging. Every command goes into **PowerShell** on Windows
(press the Windows key, type `powershell`, press Enter).

There are two things, and it helps to keep them separate in your head:

1. **map2arcpy** — the tool that *writes* ArcGIS scripts. It installs on your
   PC once and runs anywhere. It does **not** need ArcGIS.
2. **The scripts it writes** — these run *inside* ArcGIS Pro and make the
   actual map.

You install #1 once. You run #2 whenever you want a map.

---

## Part A — install the tool (once)

You only need Python 3.9 or newer. Check it's there:

```powershell
python --version
```

If that prints a version number (e.g. `Python 3.11.5`), you're set. If it says
"not recognized", install Python from https://www.python.org/downloads/ first
(tick **"Add Python to PATH"** during setup), then reopen PowerShell.

Now install map2arcpy in one line:

```powershell
pip install git+https://github.com/pinkman1007/map2arcpy.git
```

Wait for `Successfully installed map2arcpy-...`. Check it worked:

```powershell
map2arcpy --version
```

That's the whole install. You never have to do Part A again unless you want a
newer version (see Part D).

---

## Part B — make your first map

**Option 1 — the dashboard (easiest, has buttons):**

```powershell
map2arcpy serve --web
```

Your browser opens automatically. Paste the full path to a data file (or a
`.zip`, or an ArcGIS layer file) into the path box, optionally type what you
want it to show, click **Generate script**, then **Download .py**. Stop the
server later with **Ctrl+C**.

**Option 2 — one command, no browser:**

```powershell
map2arcpy generate "C:\path\to\your_data.zip" -o "$env:USERPROFILE\Documents\my_map.py"
```

Either way you end up with a `.py` file. That's the script.

---

## Part C — run the script in ArcGIS Pro

Open ArcGIS Pro. Insert ribbon → **New Notebook**. In a cell, type this one
line (point it at wherever your `.py` file is) and press **Shift+Enter**:

```python
%run "C:\Users\YOU\Documents\my_map.py"
```

Log lines scroll by; at the end the map opens in the window and a PDF is saved
next to the script. Done.

**One-time tune-up (recommended):** run `map2arcpy probe`, and it prints a
small script to run once inside ArcGIS Pro. That teaches map2arcpy about your
exact Pro version and licences, so every script it writes afterwards fits your
machine. You only do this once (or again after upgrading Pro).

---

## Part D — getting a newer version later

When a new version is released, one line updates you:

```powershell
pip install --upgrade git+https://github.com/pinkman1007/map2arcpy.git
```

Then, if the dashboard was open: stop it (Ctrl+C), start it again
(`map2arcpy serve --web`), and press **Ctrl+F5** in the browser so it loads
the fresh page.

---

## If something goes wrong

- **"map2arcpy is not recognized"** → close PowerShell, open a new one. If it
  still fails, your Python Scripts folder isn't on PATH; reinstalling Python
  with "Add to PATH" ticked fixes it.
- **A script errors on `null` or `{`** → you ran the *MapSpec (info)* text, not
  the script. Only the file ending in `.py` (starting with `#!/usr/bin/env
  python`) goes into ArcGIS Pro.
- **"Missing inputs"** → the script's data paths don't match where your files
  are; open the `.py`, fix the `DATA_DIR`/`CONFIG` paths near the top, rerun.
- **Anything else** → open an issue at
  https://github.com/pinkman1007/map2arcpy/issues with the exact message.

---

*That's it. Install once (Part A), then it's generate → run, forever.*
