"""
One-time helper to authenticate the Telegram session with your phone number.
Run this the first time to log in to your Telegram account.

Usage:
  python auth_telegram.py

It will:
  1. Ask for your phone number (defaults to ADMIN_PHONE from .env)
  2. Send an SMS/code via Telegram
  3. You enter the code
  4. A session file is created (anadata_session.session) that the backend uses

After this, just run: python main.py
"""
import os
import sys
from pathlib import Path
from pyrogram import Client
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "36041141"))
API_HASH = os.getenv("API_HASH", "192dd9c6f9a766c7880bc74a59d53d2d")
PHONE = os.getenv("ADMIN_PHONE", "+201143645282")

BASE = Path(__file__).resolve().parent
SESSION = str(BASE / "anadata_session")


def main():
    print("=" * 60)
    print("  ANA DATA — Telegram Authentication")
    print("=" * 60)
    print()
    print(f"API ID:   {API_ID}")
    print(f"API Hash: {API_HASH[:10]}...")
    print(f"Phone:    {PHONE}")
    print()

    app = Client(SESSION, api_id=API_ID, api_hash=API_HASH, phone_number=PHONE)

    with app:
        me = app.get_me()
        print()
        print("✓ Logged in successfully!")
        print(f"  Name:     {me.first_name} {me.last_name or ''}")
        print(f"  Username: @{me.username or '—'}")
        print(f"  ID:       {me.id}")
        print()
        print("Session saved at:", SESSION + ".session")
        print("You can now run: python main.py")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)
