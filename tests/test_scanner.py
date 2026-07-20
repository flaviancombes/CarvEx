from collections import Counter

from core.scanner import Scanner

scanner = Scanner(
    r"C:\Users\flavi\OneDrive\Bureau\TryPHOTOREC"
)

files = scanner.scan()

counter = Counter()

for f in files:
    counter[f.mime] += 1

print("\n===== TYPES =====\n")

for mime, count in counter.most_common():
    print(f"{mime:<40} {count}")

print("\n===== FICHIERS NON IDENTIFIÉS =====\n")

for f in files:

    if f.mime == "application/octet-stream":

        print(
            f.filename,
            "|",
            f.extension,
            "|",
            f.size,
            "octets"
        )