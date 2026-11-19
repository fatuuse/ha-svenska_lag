# Svenskalag för Home Assistant

Read-only integration mot Svenskalags officiella API. Hämtar dina kommande aktiviteter (träningar, matcher, m.m.) och visar dem i Home Assistant.

## Entiteter

| Entitet | Typ | Beskrivning |
|---|---|---|
| Nästa aktivitet | Sensor (timestamp) | Starttid för nästa aktivitet. Detaljer som titel, lag, motståndare, plats och samling finns som attribut. |
| Kommande aktiviteter | Sensor | Antal kommande, ej inställda aktiviteter de närmaste 60 dagarna. |
| Svar krävs | Binär sensor | På när det finns en kallelse utan svar och svarsfristen inte har gått ut. Listar aktiviteterna med länk till svarssidan. |
| Aktiviteter | Kalender | Alla aktiviteter i Home Assistants kalender, inställda och flyttade markeras i titeln. |

## Installation

### Via HACS (eget repo)
1. I HACS: Integrationer → menyn uppe till höger → Anpassade arkiv.
2. Lägg till din repo-URL, kategori *Integration*.
3. Installera *Svenskalag* och starta om Home Assistant.

### Manuellt
Kopiera mappen `custom_components/svenskalag` till `config/custom_components/` och starta om.

## Koppla

1. Logga in på Svenskalag och skapa en personnyckel under **Kopplingar till andra tjänster**. Nyckeln börjar med `slc_`.
2. I Home Assistant: Inställningar → Enheter & tjänster → Lägg till integration → *Svenskalag*.
3. Klistra in nyckeln.

Uppdateringsintervallet är 30 minuter.

## Begränsningar

- Integrationen kan inte svara på kallelser. API:et har ingen skrivfunktion för svar, så svar görs i Svenskalag (länken finns i attributet `reply_url`).
- Medlemslistor (`/members`) och inställningar för medlemsperioder ingår inte. De kräver andra nycklar och riktar sig till föreningsadministratörer.
- Om nyckeln återkallas visas en omautentiseringsförfrågan i Home Assistant.

## Exempel: automation

```yaml
automation:
  - alias: Påminnelse om svar på kallelse
    trigger:
      - platform: state
        entity_id: binary_sensor.svenskalag_svar_kravs
        to: "on"
    action:
      - action: notify.mobile_app_din_telefon
        data:
          title: "Svar krävs i Svenskalag"
          message: "Du har en kallelse som väntar på svar."
```

Entity-id:na beror på ditt namn. Kontrollera dem under Inställningar → Entiteter.
