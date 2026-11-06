#!/usr/bin/env python3
"""
Batch: PNG de ComfyUI -> WebP lossless preserving workflow/prompt.
Format: EXIF Make="workflow:"+JSON, EXIF Model="prompt:"+JSON.

Usage:
    png2webp_batch.py <directory> [options]

Options:
    --overwrite        Reconvert even if there is a .webp already
    --delete-png       Delete original PNG if conversion worked ok
    --jobs N           Paralel jobs (default: 1)
    --dry-run          As it says
    --require-meta     Only convert PNGs with workflow
                       (default: True; use --no-require-meta to toggle)
    --log path         write a log file (default: png2webp_batch_<date>.log
                       in current directory)
"""
import argparse
import datetime as dt
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import shutil

# ---------- logger simple to file + console ----------

class Tee:
    def __init__(self, log_path):
        self.log = open(log_path, 'w', encoding='utf-8', buffering=1)

    def write(self, msg):
        ts = dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for line in msg.splitlines() or ['']:
            full = f"[{ts}] {line}"
            print(full)
            self.log.write(full + "\n")

    def close(self):
        try:
            self.log.close()
        except Exception:
            pass


# ---------- PNG chunks reading ----------

def read_png_text_chunks(path):
    chunks = {}
    with open(path, 'rb') as f:
        if f.read(8) != b'\x89PNG\r\n\x1a\n':
            raise ValueError("not PNG")
        while True:
            lb = f.read(4)
            if len(lb) < 4:
                break
            length = int.from_bytes(lb, 'big')
            ct = f.read(4)
            data = f.read(length)
            f.read(4)
            if ct == b'tEXt':
                k, t = data.split(b'\x00', 1)
                chunks[k.decode('latin1')] = t.decode('utf-8')
            elif ct == b'iTXt':
                parts = data.split(b'\x00', 5)
                if len(parts) >= 6 and parts[1] == b'\x00':
                    chunks[parts[0].decode('latin1')] = parts[5].decode('utf-8')
            if ct == b'IEND':
                break
    return chunks


# ---------- one file conversion ----------

def convert_one(png: Path, overwrite=False, delete_png=False,
                require_meta=True, dry_run=False):
    webp = png.with_suffix('.webp')

    if webp.exists() and not overwrite:
        return {'status': 'skip_exists', 'msg': 'ya existe .webp',
                'webp': webp, 'png': png, 'stderr': ''}

    try:
        chunks = read_png_text_chunks(png)
    except Exception as e:
        return {'status': 'fail', 'msg': f'lectura PNG: {e}',
                'webp': None, 'png': png, 'stderr': ''}

    workflow_str = chunks.get("Workflow") or chunks.get("workflow")
    prompt_str = chunks.get("Prompt") or chunks.get("prompt")

    if require_meta and (not workflow_str or not prompt_str):
        return {'status': 'skip_nometa',
                'msg': f'sin workflow/prompt (chunks: {list(chunks.keys())})',
                'webp': None, 'png': png, 'stderr': ''}

    if dry_run:
        return {'status': 'ok', 'msg': '[dry-run]',
                'webp': webp, 'png': png, 'stderr': ''}

    # 2. cwebp lossless
    try:
        subprocess.run(
            ['cwebp', '-lossless', '-m', '6', '-mt',
             str(png), '-o', str(webp)],
            check=True, capture_output=True
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors='replace') if e.stderr else ''
        return {'status': 'fail',
                'msg': f'cwebp falló (rc={e.returncode})',
                'webp': None, 'png': png, 'stderr': stderr}

    # 3. metadata
    try:
        with tempfile.TemporaryDirectory() as td:
            wf_file = os.path.join(td, 'wf.txt')
            pr_file = os.path.join(td, 'pr.txt')

            with open(wf_file, 'w', encoding='utf-8') as f:
                f.write("workflow:" + (workflow_str or ""))
            with open(pr_file, 'w', encoding='utf-8') as f:
                f.write("prompt:" + (prompt_str or ""))

            r = subprocess.run(
                ['exiftool', '-overwrite_original', '-m',
                 f'-EXIF:Make<={wf_file}',
                 f'-EXIF:Model<={pr_file}',
                 str(webp)],
                capture_output=True, text=True
            )
            if r.returncode != 0:
                webp.unlink(missing_ok=True)
                return {'status': 'fail',
                        'msg': f'exiftool falló (rc={r.returncode})',
                        'webp': None, 'png': png,
                        'stderr': (r.stderr or '') + (r.stdout or '')}
    except Exception as e:
        webp.unlink(missing_ok=True)
        return {'status': 'fail', 'msg': f'exiftool: {e}',
                'webp': None, 'png': png, 'stderr': ''}

    # 4. byte to byte verification
    if workflow_str and prompt_str:
        try:
            got_wf = subprocess.run(
                ['exiftool', '-b', '-EXIF:Make', str(webp)],
                capture_output=True
            ).stdout
            got_pr = subprocess.run(
                ['exiftool', '-b', '-EXIF:Model', str(webp)],
                capture_output=True
            ).stdout
            if got_wf.endswith(b'\n'):
                got_wf = got_wf[:-1]
            if got_pr.endswith(b'\n'):
                got_pr = got_pr[:-1]

            exp_wf = ("workflow:" + workflow_str).encode('utf-8')
            exp_pr = ("prompt:" + prompt_str).encode('utf-8')

            if got_wf != exp_wf or got_pr != exp_pr:
                webp.unlink(missing_ok=True)
                return {'status': 'fail',
                        'msg': (f'verificación metadata falló '
                                f'(wf {len(got_wf)}/{len(exp_wf)} bytes, '
                                f'pr {len(got_pr)}/{len(exp_pr)} bytes)'),
                        'webp': None, 'png': png, 'stderr': ''}
        except Exception as e:
            webp.unlink(missing_ok=True)
            return {'status': 'fail', 'msg': f'verificación: {e}',
                    'webp': None, 'png': png, 'stderr': ''}

    # 5. delete PNG si se pidió
    if delete_png:
        try:
            png.unlink()
        except OSError as e:
            return {'status': 'ok',
                    'msg': f'converted, but PNG couldn't be deleted: {e}',
                    'webp': webp, 'png': png, 'stderr': ''}

    return {'status': 'ok', 'msg': '', 'webp': webp, 'png': png, 'stderr': ''}


# ---------- main ----------

def main():



    def check_dependencies():
        missing = []
        for cmd in ("cwebp", "exiftool"):
            if shutil.which(cmd) is None:
                missing.append(cmd)
        if missing:
            hints = {
                "cwebp": {
                    "linux":  "sudo apt install webp        # Debian/Ubuntu\n"
                              "sudo dnf install libwebp-tools  # Fedora\n"
                              "sudo pacman -S libwebp         # Arch",
                    "darwin": "brew install libwebp",
                    "win":    "winget install Google.CWEBP   # or add C:\\cwebp to PATH",
                },
                "exiftool": {
                    "linux":  "sudo apt install libimage-exiftool-perl",
                    "darwin": "brew install exiftool",
                    "win":    "winget install exiftool.Image.ExifToolPRO",
                },
            }
            plat = {"linux": "linux", "darwin": "darwin"}.get(
                sys.platform, "win" if sys.platform == "win32" else "linux")
            print("Missing required tools:", file=sys.stderr)
            for m in missing:
                print(f"  • {m}\n    {hints[m][plat]}", file=sys.stderr)
            sys.exit(2)

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('directory', type=Path)
    ap.add_argument('--overwrite', action='store_true')
    ap.add_argument('--delete-png', action='store_true')
    ap.add_argument('--jobs', type=int, default=1)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--require-meta', dest='require_meta',
                    action='store_true', default=True)
    ap.add_argument('--no-require-meta', dest='require_meta',
                    action='store_false')
    ap.add_argument('--log', type=Path, default=None,
                    help='log file (default: autogenerated in CWD)')
    args = ap.parse_args()

    root = args.directory
    if not root.is_dir():
        print(f"Not a directory: {root}")
        sys.exit(2)

    if args.log is None:
        stamp = dt.datetime.now().strftime('%Y%m%d_%H%M%S')
        log_path = Path.cwd() / f"png2webp_batch_{stamp}.log"
    else:
        log_path = args.log
    logger = Tee(log_path)

    try:
        logger.write(f"=== png2webp_batch ===")
        logger.write(f"directory: {root}")
        logger.write(f"Log: {log_path}")
        logger.write(f"Options: overwrite={args.overwrite} "
                     f"delete_png={args.delete_png} jobs={args.jobs} "
                     f"dry_run={args.dry_run} require_meta={args.require_meta}")

        pngs = sorted(root.rglob('*.png')) + sorted(root.rglob('*.PNG'))
        # avoid duplicates if FS isn't case-sensitive
        pngs = sorted({p.resolve(): p for p in pngs}.values())
        logger.write(f"PNGs encontrados: {len(pngs)}")
        logger.write("")

        counters = {'ok': 0, 'skip_exists': 0, 'skip_nometa': 0, 'fail': 0}
        fails = []

        def process(p):
            return convert_one(p, overwrite=args.overwrite,
                               delete_png=args.delete_png,
                               require_meta=args.require_meta,
                               dry_run=args.dry_run)

        def report(i, res):
            counters[res['status']] += 1
            rel = res['png']
            try:
                rel = rel.relative_to(root)
            except ValueError:
                pass
            line = f"[{i}/{len(pngs)}] {res['status']:>13}  {rel}"
            if res['msg']:
                line += f"  ({res['msg']})"
            logger.write(line)
            if res['status'] == 'fail':
                if res['stderr']:
                    logger.write("    --- stderr ---")
                    for sl in res['stderr'].splitlines():
                        logger.write("    " + sl)
                    logger.write("    --------------")
                fails.append(res)

        if args.jobs > 1:
            with ThreadPoolExecutor(max_workers=args.jobs) as ex:
                futs = {ex.submit(process, p): p for p in pngs}
                for i, fut in enumerate(as_completed(futs), 1):
                    report(i, fut.result())
        else:
            for i, p in enumerate(pngs, 1):
                report(i, process(p))

        logger.write("")
        logger.write("=== Summary ===")
        logger.write(f"  OK converted:      {counters['ok']}")
        logger.write(f"  Skipped (already existed): {counters['skip_exists']}")
        logger.write(f"  Skipped (no meta): {counters['skip_nometa']}")
        logger.write(f"  Failed:            {counters['fail']}")

        if fails:
            logger.write("")
            logger.write("Failed:")
            for r in fails:
                logger.write(f"  {r['png']}  ->  {r['msg']}")
            logger.write("")
            logger.write(f"Log saved in: {log_path}")
            sys.exit(1)

        logger.write("")
        logger.write(f"Log saved in: {log_path}")
        sys.exit(0)
    finally:
        logger.close()


if __name__ == '__main__':
    main()
