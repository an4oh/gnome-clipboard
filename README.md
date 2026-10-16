# clipboard-history

Cronologia appunti in stile Windows (Win+V) per GNOME su X11. Un daemon registra
ogni testo o immagine copiata; `Super+V` apre un popup vicino al puntatore con
gli ultimi elementi: click o Invio incolla nella finestra attiva, si possono
fissare (pin) o cancellare elementi, cercare nel testo, svuotare i non fissati.
Sono tenuti 25 elementi non fissati; i fissati non scadono.

Dati in `~/.local/share/clipboard-history/` (`history.db` e `images/`).

## Requisiti

- Ubuntu/GNOME in sessione **X11**
- `python3-gi`, `gir1.2-gtk-4.0`, `xdotool` (nessuna dipendenza pip)

## Installazione

```sh
./install.sh
```

Collega `bin/clipboard-history` in `~/.local/bin`, installa e avvia il servizio
utente `clipboard-history.service`, sposta `Super+V` dal vassoio notifiche
(resta `Super+M`) alla scorciatoia personalizzata "Clipboard history".
Lo script è idempotente.

Uso manuale: `clipboard-history daemon` (default) o `clipboard-history toggle`.

## Disinstallazione

```sh
./uninstall.sh
```

Ferma e rimuove il servizio, il link e la scorciatoia, restituisce `Super+V`
al vassoio notifiche. La cronologia su disco viene conservata.

## Test

```sh
python3 -m pytest tests/ -q
```

## Limite Wayland

Su Wayland l'incolla automatico non funziona: `xdotool` non può attivare
finestre né inviare Ctrl+V, e la finestra non può essere posizionata. Non è
gestito: la sessione supportata è solo X11.
