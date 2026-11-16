[简体中文](import.md) | [English](import.en.md)

# Import lists and backups

Import only files you explicitly select. Do not include passwords, authorization tokens or a full account export in a word list.

CSV/TSV headers accept `word`, `meaning`, `example`, `translation` and `scene`, plus common Chinese equivalents. Without a recognized word header, these five columns are used in order. Meanings and examples may be blank. TXT uses one word or multiword expression per line. Quote CSV cells containing commas or multiline examples.

```csv
word,meaning,example,translation,scene
bank,银行,I need to go to the bank.,我需要去银行。,办事
bank,河岸,We sat on the river bank.,我们坐在河岸边。,出游
```

These entries remain separate because their meanings differ. Identical word, meaning, example, translation and scene values merge. JSON may be a word array or an object containing `words` and `phrases`; phrase fields are `text`, `translation` and `scene`. Exported backups also retain manually selected Seen marks.

Original examples and imported material stay local and are not sent to a model or dictionary service. Voices come from the browser/system; some may use a network. The module does not bundle offline recordings.

## Material from the phone application

The [official iOS listing](https://apps.apple.com/cn/app/id698570469) has mentioned PDF export in its version history. This does not establish that every book or saved sentence can be exported in bulk, or identify the button in your installed version. Use the export/share options actually available in the client. Without a file, migration remains pending.

PDF is not parsed directly. Text PDFs can first be converted locally; scanned PDFs need OCR and checking. Review meanings, line breaks and examples, then prepare CSV/TSV/JSON/TXT. Availability of system tools such as `pdftotext` must be checked separately. This module does not install dependencies, run unconfirmed commands or bypass membership restrictions.

## Data location

Service mode saves to `data/library.json` in the installed module, or to the selected `--data-dir`. Atomic replacement prevents an invalid import from overwriting the library. Corrupt saved data produces an error rather than silently resetting to examples. Only one service instance should write a given data directory.

Static mode stores data in its browser origin. Export JSON and import it into either mode to restore it. Moving to another computer also requires transferring your backup. Listening, scrolling and finishing a slice never select Seen for you.

An exclusive lock prevents two service processes from writing one directory. After a forced termination, a stale `.server.lock` may remain; confirm no service is using the directory before removing it and restarting.
