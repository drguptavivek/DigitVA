# hash-synthetic-10k

10,000 synthetic death certificates in the WHO DORIS JSON format, made by DigitVA's `scripts/icd11-parity/make_certificates.py` from
`scripts/icd11-parity/conditions.json` (39 VA-common ICD-11 2026-01 codes with their titles and entity URIs).

`certificates.jsonl.gz`: one JSON object per line, `{"id", "group", "certificate"}`, gzip -9n. Unpacked, its sha256 is

    aa1eea021f3f7ddf389978600a43b374805ec1fb7f2d641b4afdb2575b15b9b4

and it is byte-identical to `python3 scripts/icd11-parity/make_certificates.py OUT.jsonl 10000`. `eval.sh` regenerates the file (the
first 200 lines for `quick`, all of it for `full`) and stops if the bytes differ.

Every choice comes from SHA-256 of (certificate number, field name), never from a random generator, so the file is the same on any
machine. What varies: age group (adult, child, neonate, maternal); sex (male, female, unknown); age as an estimated age, as full dates of
birth and death, or as a year-only date of birth; one to four Part I lines; zero to two Part II conditions; ten interval values
(unknown, hours, days, weeks, months, years); surgery, autopsy and manner-of-death blocks; maternal and fetal or infant blocks where
they apply. Certificates whose canonical JSON repeats are skipped, so all 10,000 are distinct.

The cause chains are random draws from the 39 conditions, so the set tests software parity (the phone engine against the WHO container
on the same input), not clinical sense.
