"""Fetch redistributable Google Fonts for local hosting, including their OFL licenses."""
from pathlib import Path
from urllib.request import Request, urlopen
import re

ROOT = Path(__file__).resolve().parents[1] / 'coffeebot' / 'static' / 'fonts'
FAMILIES = {
    'Inter': ('Inter:wght@100..900', 'inter'),
    'Fraunces': ('Fraunces:opsz,wght@9..144,100..900', 'fraunces'),
}

if __name__ == '__main__':
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, (query, folder) in FAMILIES.items():
        req = Request('https://fonts.googleapis.com/css2?family=' + query + '&display=swap',
                      headers={'User-Agent': 'Mozilla/5.0'})
        with urlopen(req, timeout=30) as response:
            css = response.read().decode()
        latin = css.rsplit('/* latin */', 1)[-1]
        urls = re.findall(r'url\((https://[^)]+\.woff2)\)', latin)
        if not urls:
            raise SystemExit(f'No WOFF2 file found for {name}; keep the system-font fallback and inspect the CSS response.')
        with urlopen(urls[-1], timeout=30) as response:
            (ROOT / (name + '.woff2')).write_bytes(response.read())
        with urlopen(f'https://raw.githubusercontent.com/google/fonts/main/ofl/{folder}/OFL.txt', timeout=30) as response:
            (ROOT / (name + '-OFL.txt')).write_bytes(response.read())
        print('Installed', name)
