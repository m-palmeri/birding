# Anki Pipelines (Split)

Scripts:
- `utils.py` — shared helpers (download, time parsing, filenames)
- `audio.py` — audio pipeline, trims & exports Anki CSV
- `visual.py` — photo pipeline, exports Anki CSV

## Inputs
- **audio**: CSV with `ML_ID, Species, ClipStart, ClipEnd, Tags`
- **visual**: CSV with `ML_ID, Species, Tags`

## Outputs
Both write: `Front, Back, Media, Species, ML, Tags`
- Audio → `Media = [sound:...]`
- Visual → `Media = <img src="...">` and the image also appears on the Front.

## Usage
```bash
# Audio
python audio.py --input audio.csv --out_dir ./out_audio --media_dir ./out_audio/media

# Visual
python visual.py --input photos.csv --out_dir ./out_visual --media_dir ./out_visual/media
```
Make sure your media ends up in Anki's `collection.media`.
Enable **Allow HTML in fields** when importing.
