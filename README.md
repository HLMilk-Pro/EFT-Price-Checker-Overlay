EFT Price Overlay using tarkov market API  https://tarkov-market.com/dev/api

Real-time Escape From Tarkov price checker with mouse-hover OCR detection and Tarkov-Market API.

📸 Preview

<img width="249" height="154" alt="image" src="https://github.com/user-attachments/assets/131ce13e-f93a-4de5-9189-a2f897a03fd1" />


⭐ Features

Lightweight on-screen overlay

Auto-detect item names via OCR screenshot scanning

Live flea + trader prices, 24h/7d trends, profit calc

Hotkeys:

F9 – Toggle detection

F10 – Show/Hide overlay

Auto-refresh Tarkov-Market data

📂 Files

main.py             # Overlay + detection + API logic
all_items.json      # Auto-cached items
data.json           # Trader price data (manual) can query all items using tarkov dev api follow the format in data.json (https://tarkov.dev/api/) [Will upload here if there are any changes on trader prices] 
config.json         # Auto-created settings
icon_templates.json # Optional OCR templates

!Only trader prices are taken from Tarkov dev since there is some wrong info with the Tarkov market!


🛠 Requirements

Python 3.10+

Install dependencies:

pip install requests pyqt6 pillow numpy opencv-python pytesseract pynput keyboard


Install Tesseract OCR
https://github.com/UB-Mannheim/tesseract/wiki

Run
python main.py

⚠️ Important Risk Disclaimer

This tool uses:

Screen capture (ImageGrab)

OCR (pytesseract)

Global mouse hooks

Always-on-top overlay

These behaviors can be flagged by Escape From Tarkov anti-cheat or violate BSG’s Terms of Service depending on their policy at any time.

✅ Not a cheat

🔍 It only reads pixels + displays API data.

❗However — YOU CAN STILL GET BANNED

Because BSG has banned overlays, injectors, macro tools, and even harmless screen-readers in the past.

✔️ Use at your own risk

I am not responsible for:

Account bans

TOS violations

API key suspension

Game crashes or performance issues

This project is for educational/test purposes only.
