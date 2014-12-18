#!/bin/sh
cd MunkiStatus

# generate localizable strings
./Localize.py --to en --genstrings "./*.{h,m,py}" --utf8

# localize nibs
./Localize.py --from en --to nl --utf8
./Localize.py --from en --to fr --utf8
./Localize.py --from en --to de --utf8
./Localize.py --from en --to es --utf8
./Localize.py --from en --to da --utf8
./Localize.py --from en --to fi --utf8
./Localize.py --from en --to it --utf8
./Localize.py --from en --to nb --utf8
./Localize.py --from en --to ru --utf8
./Localize.py --from en --to sv --utf8
./Localize.py --from en --to en_CA --utf8
./Localize.py --from en --to en_GB --utf8
./Localize.py --from en --to en_AU --utf8
