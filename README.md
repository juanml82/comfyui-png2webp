# png2webp-batch

Batch-convert ComfyUI-generated PNG images to **lossless WebP** while preserving the embedded `Workflow` and `Prompt` metadata.

ComfyUI stores workflow JSON and prompt JSON in PNG `tEXt`/`iTXt` chunks. Standard converters strip them. This script reads those chunks, converts with `cwebp -lossless`, and re-injects the data into the WebP EXIF `Make` / `Model` tags so you can recover the exact generation parameters from the final `.webp` file.

## Requirements

This is a single Python 3 script (stdlib only, **no pip packages**). It shells out to two external CLI tools that must be on your `PATH`:

| Tool | Purpose | Linux (apt/dnf/pacman) | macOS (Homebrew) | Windows |
|------|---------|------------------------|------------------|---------|
| `cwebp` | Lossless PNG → WebP encoding | `sudo apt install webp` / `sudo dnf install libwebp-tools` / `sudo pacman -S libwebp` | `brew install libwebp` | `winget install Google.CWEBP` *(ensure `C:\cwebp` is on `PATH`)* |
| `exiftool` | Read/write EXIF tags in WebP | `sudo apt install libimage-exiftool-perl` | `brew install exiftool` | `winget install exiftool.Image.ExifToolPRO` |

Verify both are available:

```bash
cwebp -version && exiftool -ver
```

## Usage
```bash
python3 png2webp_batch.py <directory> [options]
```

## Options

| Flag | Description |
|------|-------------|
| `--overwrite` | Reconvert even if a `.webp` file already exists next to the PNG. |
| `--delete-png` | Delete the original PNG after a successful conversion. |
| `--jobs N` | Number of parallel worker threads (default: `1`). Useful for large batches on multi-core machines. |
| `--dry-run` | Scan and report what *would* happen without writing any files. |
| `--require-meta` | Only convert PNGs that contain a `Workflow` chunk (default: **on**). |
| `--no-require-meta` | Toggle off the workflow requirement; convert all PNGs regardless. |
| `--log path` | Write the log to a specific file. Default: `png2webp_batch_<YYYYMMDD_HHMMSS>.log` in the current directory. |

## Examples

```bash
# Convert everything in ./output/, keep PNGs, sequential
python3 png2webp_batch.py ./output/

# Aggressive: 8 threads, delete source PNGs, overwrite existing .webp
python3 png2webp_batch.py ./output/ --overwrite --delete-png --jobs 8

# Preview what would be done (no writes)
python3 png2webp_batch.py ./output/ --dry-run

# Convert even PNGs without a Workflow chunk
python3 png2webp_batch.py ./output/ --no-require-meta

# Send log to a custom path
python3 png2webp_batch.py ./output/ --log /tmp/batch.log
```

## How it works (per file)

Read PNG text chunks – parses tEXt / iTXt blocks directly from the binary, extracting Workflow and Prompt values.
Convert – calls cwebp -lossless -m 6 -mt input.png -o output.webp.
Inject metadata – writes workflow:<json> into EXIF Make and prompt:<json> into EXIF Model via exiftool.
Verify – reads back both EXIF tags and compares byte-for-byte against the original chunk data. Mismatch → WebP is deleted, file marked as failed.
(Optional) Delete PNG – if --delete-png was passed and conversion succeeded.
At the end, a summary is printed (and logged) with counts of converted / skipped / failed files.

### Exit codes

| Code | Meaning |
|------|---------|
| `0` | All files processed successfully (or skipped). |
| `1` | One or more files failed conversion. |
| `2` | Usage error (bad arguments, missing dependency, etc.). |

## License

This project is licensed under [MIT](LICENSE).

## Support

If you find this useful, consider buying me a coffee ☕

<a href="https://ko-fi.com/juanml82"> <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Buy me a coffee on Ko-fi" /> </a>


