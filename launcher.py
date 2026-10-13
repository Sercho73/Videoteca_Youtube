"""Start the local library without installing dependencies."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
DATA = Path.home() / 'Library' / 'Application Support' / 'YouTube Biblioteca'
URL = 'http://127.0.0.1:8790/'


def running():
    try:
        with urlopen(URL + 'api/state', timeout=1) as response:
            return json.load(response).get('version') == '0.1.0'
    except (OSError, ValueError):
        return False


def main():
    os.umask(0o077)
    DATA.mkdir(parents=True, exist_ok=True)
    DATA.chmod(0o700)
    if not running():
        with (DATA / 'server.log').open('ab') as log:
            process = subprocess.Popen([sys.executable, '-m', 'youtubelibrary.server', '--data-dir', str(DATA)],
                                       cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=log, start_new_session=True)
        (DATA / 'server.pid').write_text(str(process.pid))
        for _ in range(50):
            if running():
                break
            if process.poll() is not None:
                raise SystemExit('No se pudo iniciar Videoteca. Revisa ' + str(DATA / 'server.log'))
            time.sleep(.1)
        else:
            raise SystemExit('Videoteca no responde. Revisa ' + str(DATA / 'server.log'))
    if '--no-browser' not in sys.argv:
        subprocess.run(['open', URL], check=True)
    print('Videoteca: ' + URL)


if __name__ == '__main__':
    main()
