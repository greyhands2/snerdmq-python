import os
import platform
import urllib.request
import stat
import sys

REPO = 'speed-nerd/snerdmq'
VERSION = 'v0.1.1'

def main():
    system = platform.system().lower()
    machine = platform.machine().lower()

    platform_map = {
        'darwin': 'macos',
        'linux': 'linux',
        'windows': 'windows'
    }

    arch_map = {
        'x86_64': 'x64',
        'amd64': 'x64',
        'aarch64': 'arm64',
        'arm64': 'arm64'
    }

    plat = platform_map.get(system)
    arch = arch_map.get(machine)

    if not plat or not arch:
        print(f"[Snerd] Unsupported platform/arch: {system} {machine}", file=sys.stderr)
        print("[Snerd] You must manually compile and provide the snerdmq binary path.")
        sys.exit(0)

    ext = '.exe' if plat == 'windows' else ''
    binary_name = f"snerdmq-{plat}-{arch}{ext}"
    download_url = f"https://github.com/{REPO}/releases/download/{VERSION}/{binary_name}"

    # Determine where to put the binary (inside the package directory)
    package_dir = os.path.dirname(os.path.abspath(__file__))
    bin_dir = os.path.join(package_dir, 'bin')
    bin_dest = os.path.join(bin_dir, f'snerdmq{ext}')

    os.makedirs(bin_dir, exist_ok=True)

    print(f"[Snerd] Downloading pre-compiled engine from GitHub: {binary_name}...")

    try:
        req = urllib.request.Request(download_url)
        with urllib.request.urlopen(req) as response, open(bin_dest, 'wb') as out_file:
            out_file.write(response.read())
        
        # Make executable on Unix
        if plat != 'windows':
            st = os.stat(bin_dest)
            os.chmod(bin_dest, st.st_mode | stat.S_IEXEC)
            
        print("[Snerd] Successfully installed Snerd Engine!")

    except urllib.error.HTTPError as e:
        if e.code == 404:
            print(f"\n[Snerd] WARN: Binary not found at {download_url}")
            print("[Snerd] (This is expected if you haven't published a GitHub Release yet)")
            print("[Snerd] Please provide binary_path manually when initializing SnerdQueue.\n")
        else:
            print(f"[Snerd] Failed to download binary: HTTP {e.code} {e.reason}", file=sys.stderr)
    except Exception as e:
        print(f"[Snerd] Failed to download binary: {e}", file=sys.stderr)

if __name__ == '__main__':
    main()
