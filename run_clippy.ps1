# Helper to run Clippy with your chosen defaults
# Edit values below to match your broadcaster name and any overrides
$env:TWITCH_CLIENT_ID="jy9770gh3w9c2szccdh1yjgaedxklv"; $env:TWITCH_CLIENT_SECRET="6wqhilria7ffnumzu9uuizuyobbxdp"; python .\main.py --broadcaster <your_twitch_login> --clips 12 --compilations 2 --min-views 1 --max-concurrency 4 -y --quality balanced --fps 60 --audio-bitrate 192k --resolution 1920x1080 --transition-prob 0.35
