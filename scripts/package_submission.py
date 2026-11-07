"""Create a source-only archive using an allowlist; never include .env or .venv."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FILES = ['app.py', 'README.md', 'requirements.txt', 'requirements-dev.txt',
         'requirements-lock.txt', 'render.yaml', '.env.example', '.gitignore']
FOLDERS = ['coffeebot', 'sql', 'scripts', 'tests', 'docs']

if __name__ == '__main__':
    target = ROOT.parent / 'CoffeeBot_Hubs_Source.zip'
    files = [ROOT / name for name in FILES if (ROOT / name).is_file()]
    for folder in FOLDERS:
        files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file()
                     and '__pycache__' not in p.parts and p.suffix != '.pyc')
    with ZipFile(target, 'w', ZIP_DEFLATED) as archive:
        for file in sorted(files):
            archive.write(file, 'coffeebot-hubs/' + file.relative_to(ROOT).as_posix())
    print(f'Created {target.name} with {len(files)} source files. Secrets, environments and QA artifacts excluded.')
