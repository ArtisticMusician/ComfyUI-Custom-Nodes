"""Point ComfyUI at this pack, reload it, and check it came up changed.

    python tools/reload_comfyui.py                  # link, and report what the server has
    python tools/reload_comfyui.py --restart        # also reload it (it goes down and up)
    python tools/reload_comfyui.py --url http://127.0.0.1:8188

Why it exists: editing a file in this repo changes nothing in a running ComfyUI. Node classes
are imported once at startup, so every change needs the server to reload - and a browser
refresh is not that.

Reloading takes the server down and brings it back, which interrupts whatever is on the canvas,
so it happens only when --restart is given. Without it this script changes nothing: it links,
reads the live definitions back, and says whether they match this repo.

What it does:

1. Link  - makes the Music install's custom_nodes/OneSoloStudios point at this repo (the
           only install that loads this pack). Editing the repo then edits what ComfyUI imports;
           no copying, so a copy cannot go stale.
2. Check - asks the running server what it actually has, before touching it.
3. Reload- with --restart, POSTs ComfyUI-Manager's /v2/manager/reboot, which re-execs the
           server process in place, then waits for it to answer again.
4. Verify- reads the definitions back and reports pass/fail per expectation.

Exit code 0 when every check passes, 1 otherwise, so it can be used as a gate.
"""

import argparse
import json
import subprocess
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

INSTANCE = Path(r"M:\ComfyUI_installs\Music\ComfyUI")   # the only install that loads this pack
REPO = Path(r"D:\ComfyUI_Nodes")
LINK_NAME = "OneSoloStudios"
DEFAULT_URL = "http://127.0.0.1:8188"

# What the pack's savers must look like once the reload has landed. Read from the live
# server, so this is the only place that says what "correct" means.
EXPECT_DEFAULTS = {
    "AudioSave": {"timestamp": False, "float32": True},
    "StemSave": {"timestamp": False, "float32": True},
}
EXPECT_ABSENT_FROM = {"StemEnsemble": ["UVR way"]}


def get_json(url, timeout=10):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def post(url, payload=None, timeout=30):
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status


def make_link(link, repo):
    """A junction on Windows: a directory symlink needs a privilege this usually does not
    have, while a junction needs none and is followed exactly the same way."""
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(repo)],
                              capture_output=True, text=True)
    os.symlink(repo, link, target_is_directory=True)
    return None


def link_instance():
    """Point the Music install's custom_nodes at this repo: a junction, so editing the repo
    edits what ComfyUI imports, and a copy can never go stale. Nothing else is touched - the
    other installs do not load this pack."""
    nodes = INSTANCE / "custom_nodes"
    if not nodes.is_dir():
        print(f"link   : {nodes} is not there")
        return False
    link = nodes / LINK_NAME
    if link.exists() or link.is_symlink():
        target = os.path.realpath(link)
        if os.path.normcase(target) == os.path.normcase(str(REPO)):
            print(f"link   : {INSTANCE.parent.name} {LINK_NAME} ok")
            return True
        print(f"link   : {INSTANCE.parent.name} {LINK_NAME} points at {target}, not this repo")
        return False
    result = make_link(link, REPO)
    if link.exists() or link.is_symlink():
        print(f"link   : {INSTANCE.parent.name} {LINK_NAME} created -> {REPO}")
        return True
    why = (result.stderr or result.stdout).strip() if result else "refused"
    print(f"link   : {INSTANCE.parent.name} could not create the link ({why})")
    print(f"         run once in an admin prompt: mklink /J \"{link}\" \"{REPO}\"")
    return False


def node_inputs(info, name):
    """ComfyUI's real shape: {name: {input: {required/optional: {input: [type, options]}}}}."""
    inputs = {}
    entry = info.get(name) or {}
    for section in ("required", "optional"):
        for input_name, spec in (entry.get("input") or {}).get(section, {}).items():
            options = spec[1] if isinstance(spec, list) and len(spec) > 1 else {}
            inputs[input_name] = (spec[0] if isinstance(spec, list) else spec, options or {})
    return inputs


def node_defaults(info, name):
    return {input_name: (options.get("default") if isinstance(options, dict) else None)
            for input_name, (_, options) in node_inputs(info, name).items()}


def check(url, label):
    """Read the live definitions and report each expectation. Returns the failures."""
    failures = []
    for node, expected in EXPECT_DEFAULTS.items():
        try:
            info = get_json(f"{url}/object_info/{node}")
        except urllib.error.URLError as exc:
            failures.append(f"{node}: could not be read ({exc})")
            print(f"{label}: {node:11} unreadable")
            continue
        defaults = node_defaults(info, node)
        for key, want in expected.items():
            got = defaults.get(key)
            ok = got is want
            print(f"{label}: {node:11} {key:9} default {str(got):5} expected {str(want):5} "
                  f"{'ok' if ok else 'STALE'}")
            if not ok:
                failures.append(f"{node}.{key} is {got}, expected {want}")
    for node, absent in EXPECT_ABSENT_FROM.items():
        try:
            info = get_json(f"{url}/object_info/{node}")
        except urllib.error.URLError as exc:
            failures.append(f"{node}: could not be read ({exc})")
            continue
        choices = []
        for _, (kind, _options) in node_inputs(info, node).items():
            if isinstance(kind, list):          # a COMBO: the list IS the choices
                choices += [str(choice) for choice in kind]
        for needle in absent:
            found = [choice for choice in choices if needle.lower() in choice.lower()]
            gone = not found
            print(f"{label}: {node:11} offers '{needle}'  "
                  f"{'gone' if gone else 'still there: ' + repr(found)}")
            if not gone:
                failures.append(f"{node} still offers {found}")
    return failures


def wait_for(url, timeout=300):
    """After a reboot the process is gone for a few seconds. Wait for it to answer."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            get_json(f"{url}/system_stats", timeout=5)
            return True
        except Exception:
            time.sleep(2)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=os.environ.get("COMFYUI_URL", DEFAULT_URL),
                        help=f"the running ComfyUI (default {DEFAULT_URL})")
    parser.add_argument("--restart", action="store_true",
                        help="ask the server to reload. ComfyUI comes back with the new code, "
                             "but it goes down and up, which interrupts whatever is on canvas, "
                             "so it only happens when this flag is given")
    args = parser.parse_args()
    url = args.url.rstrip("/")

    print(f"repo   : {REPO}")
    link_instance()

    # It may be mid-start or mid-restart, so give it a window to answer instead of calling it
    # down on the first try: a server relaunching under its app takes a while to come back.
    if not wait_for(url, timeout=180):
        print(f"\nserver : nothing answering at {url} after 180s")
        print("         start ComfyUI, then run this again")
        return 1
    print(f"\nserver : {url} is up")

    failures = check(url, "before")
    if not args.restart:
        if failures:
            print(f"\n{len(failures)} check(s) failing")
            print("nothing was changed. This server reloads only when asked to:")
            print(f"    python {Path(__file__).name} --restart")
            return 1
        print("\nnothing to do - the running server already matches this repo")
        return 0

    print("\nreload : asking the server to restart itself")
    try:
        post(f"{url}/v2/manager/reboot")
    except urllib.error.HTTPError as exc:
        print(f"reload : refused ({exc.code} {exc.reason}). ComfyUI-Manager may be off, or its")
        print("         security level is above 'middle'. Restart ComfyUI by hand.")
        return 1
    except urllib.error.URLError as exc:
        if isinstance(exc, urllib.error.HTTPError):
            raise
        print(f"reload : the connection dropped as it went down "
              f"({exc.__class__.__name__}) - expected")
    except OSError as exc:
        # The server re-execs itself inside the same process, so the connection dies
        # mid-response. That is the reload working, not a failure.
        print(f"reload : the connection dropped as it went down "
              f"({exc.__class__.__name__}) - expected")

    print("reload : waiting for it to come back")
    if not wait_for(url):
        print("reload : it did not come back. Start ComfyUI again by hand.")
        return 1
    print("reload : back up")

    failures = check(url, "after ")
    if failures:
        print("\nSTILL STALE:")
        for line in failures:
            print(f"  - {line}")
        return 1
    print("\nreloaded, and the live server matches this repo")
    return 0


if __name__ == "__main__":
    sys.exit(main())
