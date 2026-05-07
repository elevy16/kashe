#!/usr/bin/env python3
"""Simulate MindBody sending class attendance webhooks to the Kashé API."""

import json
import time

import requests

BASE = "http://127.0.0.1:5000/api/webhook/mindbody"

EVENTS = [
    {
        "mindbody_email": "esther@test.com",
        "class_name": "Cardio Crush",
        "studio_name": "SoulCycle West Hollywood",
        "attended_at": "2026-05-07T09:00:00",
    },
    {
        "mindbody_email": "esther@test.com",
        "class_name": "Pilates Powerhouse",
        "studio_name": "Club Pilates",
        "attended_at": "2026-05-07T10:30:00",
    },
    {
        "mindbody_email": "riva@test.com",
        "class_name": "Yoga Flow Journey",
        "studio_name": "CorePower Yoga",
        "attended_at": "2026-05-07T11:00:00",
    },
    {
        "mindbody_email": "esther@test.com",
        "class_name": "Cardio Crush",
        "studio_name": "SoulCycle West Hollywood",
        "attended_at": "2026-05-07T17:00:00",
    },
    {
        "mindbody_email": "riva@test.com",
        "class_name": "Barre Basics",
        "studio_name": "Pure Barre",
        "attended_at": "2026-05-07T18:00:00",
    },
]


def main():
    for i, payload in enumerate(EVENTS, start=1):
        print(f"\n--- Event {i} ---")
        print(f"POST {BASE}")
        print(json.dumps(payload, indent=2))
        try:
            r = requests.post(
                BASE,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30,
            )
            print(f"HTTP {r.status_code}")
            try:
                print(json.dumps(r.json(), indent=2))
            except ValueError:
                print(r.text)
        except requests.RequestException as e:
            print(f"Request failed: {e}")
        if i < len(EVENTS):
            time.sleep(1)


if __name__ == "__main__":
    main()
