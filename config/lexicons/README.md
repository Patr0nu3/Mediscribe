# Word lists

Each file is a JSON array with one word per entry. Matching ignores case and
punctuation except apostrophes. Restart the pipeline or editor after changes.

| File | Used for |
|------|----------|
| [backchannels.json](backchannels.json) | Short acknowledgements such as "yeah" and "mm-hmm". Fusion checks their speaker against voice embeddings. |
| [nonfinal_words.json](nonfinal_words.json) | Words such as "and" and "the" that usually continue a sentence. Fusion reduces the likelihood of a speaker change after them. |

Add or remove entries directly:

```json
[
  "yeah",
  "mm-hmm",
  "okay"
]
```

An empty array disables the corresponding word list. Missing or invalid files
raise an error. The backchannel list follows the Switchboard acknowledgement
inventory and common conversational continuers.
