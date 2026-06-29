# AIS Data Providers — Coverage Research

Investigated 2026-06-28. Goal: find a free AIS data source with coverage for Novorossiysk port (Black Sea, ~44.7°N 37.8°E).

## Current Provider: AISstream.io

- **Status**: ❌ No coverage for Novorossiysk / Black Sea
- **Confirmed**: WebSocket connects and stays open, but zero messages received for any bounding box in the Black Sea area — even a 200×200 km box. English Channel returns data instantly with the same API key, confirming coverage is the issue, not the key or code.
- **Format note**: AISstream expects bounding boxes as `[[max_lat, min_lon], [min_lat, max_lon]]` (top-left → bottom-right). The original code had them reversed; this was fixed.
- **Free tier**: Yes — free WebSocket streaming
- **Conclusion**: Keep subscription for potential future coverage expansion, but cannot use as primary source for this project.

## Providers Evaluated

| Provider | Free tier | Black Sea coverage | Area query | Real-time | Notes |
|---|---|---|---|---|---|
| AISstream.io | ✅ free | ❌ none | ✅ WebSocket bbox | ✅ | Current provider, no coverage |
| MarineTraffic | 100 credits/mo | ✅ | ✅ PS01 area query | ✅ | Best option — see issue #1 |
| VesselFinder | 0 credits | unknown | ✅ LiveData (paid sub) | ✅ | No free usage available |
| Global Fishing Watch | ✅ free | ✅ satellite global | ⚠️ aggregated grids | ❌ historical | Fishing vessels only; not real-time |
| AISHub | ✅ free | unknown | ✅ | ✅ | Requires contributing own AIS station — not applicable |

## Recommended Path: MarineTraffic

MarineTraffic free developer plan includes **100 credits/month**. Their `PS01` (Vessels in Area) endpoint returns all vessel positions within a bounding box.

**Limitation**: 100 credits/month is not enough for continuous 30-min polling (would exhaust in ~2 days). Options:
- Use as a supplement/fallback when AISstream returns nothing
- Upgrade to a paid plan if the project scales
- Use sparingly: manual trigger only, not scheduled polling

## Alternative: RTL-SDR Hardware Receiver

Since the user lives near Novorossiysk port (~10-20 km), AIS radio signals (VHF 161.975 / 162.025 MHz) from vessels are directly receivable.

**Hardware needed**: RTL-SDR Blog V4 dongle (~$25-35) + included antenna  
**Software**: `rtl_ais` → outputs NMEA sentences over UDP → decode in `vessel_tracker.py`  
**Cost after hardware**: $0 forever, no API limits, no coverage gaps  

This is the most robust long-term solution if continuous free real-time tracking is needed.
