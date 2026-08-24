# Third-party data notices

## ECDICT

The bundled CET-4/CET-6 vocabulary is derived from the `cet4`/`cet6`-tagged
entries and the foundational `zk`/`gk` school-vocabulary prerequisites in
[skywind3000/ECDICT](https://github.com/skywind3000/ECDICT).

- Source file: `ecdict.csv`
- Filter: rows whose space-separated `tag` field contains `zk`, `gk`, `cet4`,
  or `cet6`
- License: MIT
- Included license: `shared/content/licenses/LICENSE-ECDICT.txt`

The generated word count and extraction date are recorded in
`shared/content/catalog-manifest.json`.

## Example sentences

The bundled structured examples are derived from the following sources.

- Tatoeba English-Chinese sentence pairs, released under CC BY 2.0. Attribution:
  Tatoeba Project and ManyThings.org. The source description is retained in
  `shared/content/licenses/NOTICE-TATOEBA.txt`.
- WordNet 3.0, Copyright 2006 Princeton University. The WordNet permission and
  disclaimer are included in `shared/content/licenses/LICENSE-WORDNET.txt`.
- Brown Corpus, W. N. Francis and H. Kucera, distributed with permission of
  the copyright holder, redistribution permitted. See
  `shared/content/licenses/NOTICE-BROWN.txt`.
- Project Gutenberg public-domain selections. See
  `shared/content/licenses/NOTICE-GUTENBERG.txt`.

LexiTrack only retains a reference example when both its English sentence and
Chinese translation are non-empty. Entries with fewer than three complete
pairs are supplemented by original curriculum fallback sentences authored for
this project and explicitly marked `LexiTrack curriculum fallback` in the
catalog provenance. The clients require no corpus package or network access at
runtime.
