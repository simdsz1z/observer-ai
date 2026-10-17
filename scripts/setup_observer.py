"""Install pinned official Qwen weights and llama.cpp locally. No AI service is used."""
import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = "b11669"
HELPER_URL = "https://github.com/simdsz1z/observer-ai/releases/download/v0.3.0/observer-runtime-windows-x64.exe"
HELPER_SIZE = 179712
HELPER_SHA256 = "7fc1249739e1996d62311918cdc55006d9e6e449c7095802db3a09923f715653"
RUNTIME_SHA256 = "2c07574e7bde71321cb785282b20cc821e951132149eeceeea32ddebdbf0598e"
FILES = [
    ("Qwen3VL-2B-Instruct-Q4_K_M.gguf", 1107409952,
     "089d75c52f4b7ffc56ba998ffc50aae89fcafc755f9e7208aacca281dca6c2ae"),
    ("mmproj-Qwen3VL-2B-Instruct-Q8_0.gguf", 445053216,
     "f9a68fabba69c3b81e153367b2c7521030b0fa8bb0de400c9599c8e6725f9c82"),
]


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def download(url, destination, expected_size=None, expected_hash=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and (not expected_size or destination.stat().st_size == expected_size):
        if not expected_hash or digest(destination) == expected_hash:
            print(f"Verified existing {destination.name}", flush=True)
            return destination
    part = destination.with_suffix(destination.suffix + ".part")
    for attempt in range(4):
        try:
            offset = part.stat().st_size if part.exists() else 0
            request = urllib.request.Request(url, headers={"User-Agent": "ObserverAI-local-setup/0.3", **({"Range": f"bytes={offset}-"} if offset else {})})
            with urllib.request.urlopen(request, timeout=45) as response:
                if offset and response.status != 206:
                    offset = 0
                total = expected_size or (int(response.headers.get("Content-Length", 0)) + offset)
                written, last_report = offset, 0.0
                with part.open("ab" if offset else "wb") as stream:
                    while block := response.read(1024 * 1024):
                        stream.write(block)
                        written += len(block)
                        if time.monotonic() - last_report >= 10:
                            print(f"{destination.name}: {written / 1024**2:.0f} / {total / 1024**2:.0f} MB", flush=True)
                            last_report = time.monotonic()
            if expected_size and part.stat().st_size != expected_size:
                raise OSError("Incomplete download")
            if expected_hash and digest(part) != expected_hash:
                part.unlink()
                raise OSError("SHA-256 verification failed")
            part.replace(destination)
            print(f"Verified download {destination.name}", flush=True)
            return destination
        except Exception as error:
            if attempt == 3:
                raise
            print(f"Retrying {destination.name}: {type(error).__name__}", flush=True)
            time.sleep(1 + attempt)


def download_large(url, destination, size, sha):
    """Bounded parallel ranges avoid slow single-connection model downloads."""
    if destination.exists() and destination.stat().st_size == size and digest(destination) == sha:
        print(f"Verified existing {destination.name}", flush=True)
        return destination
    directory = destination.parent / (destination.name + ".segments")
    directory.mkdir(parents=True, exist_ok=True)
    chunk_size = 64 * 1024 * 1024
    ranges = [(i, start, min(size - 1, start + chunk_size - 1)) for i, start in enumerate(range(0, size, chunk_size))]
    previous = destination.with_suffix(destination.suffix + ".part")
    if previous.exists():
        with previous.open("rb") as source:
            for index, start, end in ranges:
                remaining = min(end - start + 1, previous.stat().st_size - start)
                if remaining <= 0:
                    break
                part = directory / f"{index:03}.part"
                if not part.exists():
                    with part.open("wb") as target:
                        source.seek(start)
                        while remaining:
                            block = source.read(min(1024 * 1024, remaining))
                            if not block:
                                break
                            target.write(block)
                            remaining -= len(block)

    def segment(item):
        index, start, end = item
        path = directory / f"{index:03}.part"
        for attempt in range(5):
            have = path.stat().st_size if path.exists() else 0
            if have == end - start + 1:
                return path
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "ObserverAI-local-setup/0.3", "Range": f"bytes={start + have}-{end}"})
                with urllib.request.urlopen(request, timeout=45) as response:
                    if response.status != 206 or not response.headers.get("Content-Range", "").startswith(f"bytes {start + have}-"):
                        raise OSError("Server did not honor the requested download range")
                    with path.open("ab" if have else "wb") as target:
                        while block := response.read(1024 * 1024):
                            target.write(block)
                if path.stat().st_size != end - start + 1:
                    raise OSError("Incomplete range")
                print(f"{destination.name}: segment {index + 1}/{len(ranges)} complete", flush=True)
                return path
            except Exception:
                if attempt == 4:
                    raise
                time.sleep(attempt + 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        parts = list(executor.map(segment, ranges))
    assembled = destination.with_suffix(destination.suffix + ".assembling")
    with assembled.open("wb") as target:
        for part in parts:
            with part.open("rb") as source:
                shutil.copyfileobj(source, target, 4 * 1024 * 1024)
    if assembled.stat().st_size != size or digest(assembled) != sha:
        assembled.unlink(missing_ok=True)
        raise OSError("Assembled model SHA-256 mismatch")
    assembled.replace(destination)
    for part in parts:
        part.unlink()
    directory.rmdir()
    previous.unlink(missing_ok=True)
    print(f"Verified download {destination.name}", flush=True)
    return destination


def install():
    model_dir = ROOT / ".models" / "qwen3-vl-2b-instruct"
    runtime_dir = ROOT / ".runtime" / f"llama-{RELEASE}-vulkan"
    archive = ROOT / ".runtime" / f"llama-{RELEASE}-bin-win-vulkan-x64.zip"
    tasks = [(f"https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct-GGUF/resolve/main/{name}", model_dir / name, size, sha)
             for name, size, sha in FILES]
    tasks.append((f"https://github.com/ggml-org/llama.cpp/releases/download/{RELEASE}/{archive.name}", archive, None, RUNTIME_SHA256))
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(download_large if task[2] else download, *task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            future.result()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as package:
        for member in package.infolist():
            target = (runtime_dir / member.filename).resolve()
            if not target.is_relative_to(runtime_dir.resolve()):
                raise ValueError("Unsafe runtime archive path")
        package.extractall(runtime_dir)
    executable = next(runtime_dir.rglob("llama-mtmd-cli.exe"), None)
    if executable is None:
        raise RuntimeError("The official runtime archive did not contain llama-mtmd-cli.exe")
    helper = executable.parent / "observer-runtime.exe"
    download(HELPER_URL, helper, HELPER_SIZE, HELPER_SHA256)
    manifest = {"helper": str(helper), "helper_sha256": HELPER_SHA256,"model": "Qwen3-VL-2B-Instruct", "runtime_release": RELEASE,
                "runtime_archive_sha256": digest(archive), "executable": str(executable),
                "model_path": str(model_dir / FILES[0][0]), "projector_path": str(model_dir / FILES[1][0]),
                "files": [{"name": name, "size": size, "sha256": sha} for name, size, sha in FILES]}
    (ROOT / ".runtime" / "observer-install.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print("Local Qwen observer installed and verified.", flush=True)
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This installer currently provides the Windows x64 runtime.")
    install()
