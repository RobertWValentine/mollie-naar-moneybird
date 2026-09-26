#!/bin/bash
# Draait één synchronisatieronde. Wordt aangeroepen door launchd of cron.
#
# Waarden uit de omgeving winnen van .env, zodat je een enkele instelling kunt
# overrulen zonder het bestand aan te passen. Andersom zou een test met een
# afwijkende instelling stilletjes de gewone waarden gebruiken.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
    while IFS='=' read -r sleutel waarde; do
        case "$sleutel" in
            ''|\#*) continue ;;
        esac
        if [[ ! "$sleutel" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
            continue
        fi
        if [ -z "${!sleutel+gezet}" ]; then
            export "$sleutel=$waarde"
        fi
    done < .env
fi

exec python3 -m mollie_moneybird_sync "$@"
