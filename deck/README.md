# Rushover: deck

`content.json` holds all slide text and speaker notes. Everything else is generated from it.

## Build

```
python -m pip install python-pptx
python deck/build_deck.py        # from the project root, or: cd deck && python build_deck.py
```

Writes `Rushover.pptx` (no speaker notes in the file) and `SCRIPT.md` (script per slide, word counts, time at 150 wpm against 5:00).

## Edit the text

```
python deck/serve.py             # optional port: python deck/serve.py 5191
```

Open http://127.0.0.1:5190. Edit any field, watch the word count and time, then "Save and rebuild". The previous `content.json` is copied to `history/` first. The server listens on 127.0.0.1 only and serves files inside `deck/` only.

## Upload to Google Slides

Either: Google Slides > File > Import slides > Upload > pick the .pptx, select all slides, Import.
Or: upload the .pptx to Google Drive, right-click > Open with > Google Slides.

The deck uses Inter and Roboto Mono, which both exist in Google Slides. Speaker notes come across into the notes pane.
