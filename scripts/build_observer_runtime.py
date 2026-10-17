"""Build the local pipe helper with installed MSVC against the exact shipped DLLs."""
import argparse
from pathlib import Path
import os
import re
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime" / "llama-b11669-vulkan"
BUILD = ROOT / ".runtime" / "observer-build"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", action="store_true")
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    if not args.compile:
        paths = {"llama.h": "include/llama.h", "mtmd.h": "tools/mtmd/mtmd.h", "mtmd-helper.h": "tools/mtmd/mtmd-helper.h"}
        for name in ["ggml.h", "ggml-cpu.h", "ggml-backend.h", "ggml-opt.h", "gguf.h", "ggml-alloc.h"]:
            paths[name] = "ggml/include/" + name
        for name, path in paths.items():
            target = BUILD / name
            if not target.exists():
                target.write_bytes(urllib.request.urlopen("https://raw.githubusercontent.com/ggml-org/llama.cpp/b11669/" + path).read())
        target = BUILD / "json.hpp"
        if not target.exists():
            target.write_bytes(urllib.request.urlopen("https://raw.githubusercontent.com/nlohmann/json/v3.12.0/single_include/nlohmann/json.hpp").read())
        vswhere = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
        folder = subprocess.check_output([str(vswhere), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-property", "installationPath"], text=True).strip()
        if not folder:
            raise SystemExit("MSVC Build Tools are required to rebuild the helper.")
        vcvars = Path(folder) / "VC/Auxiliary/Build/vcvars64.bat"
        command = f'call "{vcvars}" >nul && "{sys.executable}" "{Path(__file__).resolve()}" --compile'
        subprocess.run('cmd.exe /d /s /c "' + command + '"', check=True, cwd=BUILD)
        return
    libraries = []
    for name in ["llama", "mtmd", "ggml", "ggml-base"]:
        output = subprocess.check_output(["dumpbin", "/nologo", "/exports", str(RUNTIME / (name + ".dll"))], text=True)
        exports = re.findall(r"^\s*\d+\s+[0-9A-F]+\s+[0-9A-F]+\s+(\S+)", output, re.M)
        definition = BUILD / (name + ".def")
        definition.write_text(f"LIBRARY {name}.dll\nEXPORTS\n" + "\n".join(exports))
        library = BUILD / (name + ".lib")
        subprocess.run(["lib", "/nologo", "/machine:x64", "/def:" + str(definition), "/out:" + str(library)], check=True)
        libraries.append(str(library))
    subprocess.run(["cl", "/nologo", "/std:c++17", "/EHsc", "/O2", "/MD", "/utf-8", "/I" + str(BUILD),
                    str(ROOT / "native/observer_runtime.cpp"), *libraries, "/Fe:" + str(RUNTIME / "observer-runtime.exe")], check=True, cwd=BUILD)
    print("Built persistent local observer runtime.")


if __name__ == "__main__":
    main()
