# Localization roadmap (phase 2)

Status: implemented (this is the design that the phase-2 PR carries out). Phase 1 (single-parser source unification, issue #3) shipped first and is a prerequisite.

## Breaking changes (for release notes - bump to a major version)

Sensor state values changed from English prose to stable slugs. The frontend now
localizes them per user via `translations/<lang>.json`. Recorder history cannot be
rewritten, so old rows keep the old strings; automations/templates/cards matching
the old text must be updated.

| Sensor | Old state (example) | New state |
|--------|--------------------|-----------|
| Weather Condition | `Light Rain` | `light_rain` (localized for display) |
| Cloud Coverage State | `Few (1-2 oktas)` | `few` (ENUM, localized) |
| Cloud Coverage Type | `Cumulonimbus` | `cumulonimbus` (ENUM, localized) |
| Auto Indicator | `Auto Report` / `Manual Report` | `auto` / `manual` (ENUM) |
| CAVOK | `True` / `False` | `yes` / `no` (ENUM) |
| Runway `<id>` State | `Clear and dry, coverage: ...` | surface slug (ENUM, localized); coverage (localized) / depth / friction moved to attributes |
| Cloud Layers (composite string) | `Few (1-2 oktas) 5000ft, Broken (5-7 oktas) 10000ft` | `few 5000ft, broken 10000ft` (plain string built from slugs, not localized) |
| All Runways State (composite string) | `Runway 24L: Damp, Coverage: 11-25%, ...` | `Runway 24L: damp, Coverage: cov_11_25, ...` (plain string built from slugs, not localized) |
| Trend | `No significant change` | `NOSIG` (raw, language-neutral) |

The two composite-string sensors (Cloud Layers, All Runways State) remain plain strings (they are not enumerable); their embedded values are now slugs. The per-field ENUM sensors above are the localized ones.

New languages or weather combinations: edit `scripts/build_translations.py` and run
`python scripts/build_translations.py` to regenerate `translations/<lang>.json`.

## Goal

Make weather/cloud/runway sensor states language-independent and localized per user, the Home-Assistant-idiomatic way: the integration emits a stable machine slug as the state; HA's frontend translates it to the viewing user's language via `translations/<lang>.json`. The integration stops baking English (or any single language) prose into the state.

This is what actually closes issue #3 for the reporter (French) and removes the dead `translations_data.py`. PR #2's French belongs in `translations/fr.json` under this design, not in `translations_data.py`.

## Why slugs, not prose

- State stays identical across languages and across both data sources, so recorder history, statistics and automations stay clean.
- Localization is per logged-in user (frontend), not just the system language. Self-translation in Python can only ever follow `hass.config.language` (system), never per-user.
- It is the mechanism HA core uses (e.g. DSMR: `device_class=ENUM`, `options=['low','normal']`, `translation_key`, strings under `entity.sensor.<key>.state.<slug>`).

## Two mechanisms, by vocabulary type

1. Finite vocabulary -> `SensorDeviceClass.ENUM` + `options=[slugs]` + `translation_key`. HA validates the value is in `options` (ValueError otherwise) and the frontend localizes it. Cannot be combined with `state_class` or `native_unit_of_measurement` (these sensors have neither, so this is fine).
2. Compositional / open-ended (weather phenomena) -> stays a plain string sensor with a stable canonical token state; localized prose and the structured breakdown go in attributes. Do NOT force this into an ENUM: the combination space is unbounded and out-of-options values (severe weather like `+FZRASN`, `+TSGR`) would be rejected/nulled by HA.

## Wiring note (important)

Today the sensors set `_attr_name` manually and have NO `translation_key`, so the `entity.sensor.*` block already present in `translations/en.json` is not actually driving state translation. Phase 2 must set `translation_key` on each ENUM sensor description for state translation to take effect. The existing `entity.sensor` block is also partly stale (keys `cloud_coverage`, `report_type`, `recent_weather`, `wind_shear`, `remarks` do not match real sensor keys; `runway_state.state_attributes` lists slugs the code never emits) and should be reconciled to the real keys below.

## Slug vocabulary

`const.py` becomes the single source of truth for `code -> slug`. Display strings (including English) live only in `translations/<lang>.json`. Delete the per-language dicts in `translations_data.py`.

### Cloud coverage (ENUM, sensor key `cloud_coverage_state`, translation_key `cloud_coverage_state`)

| METAR | slug | en |
|-------|------|----|
| (no layers) | `clear` | Clear |
| SKC | `skc` | Clear sky |
| CLR | `clr` | No clouds below 12,000 ft |
| NSC | `nsc` | No significant clouds |
| NCD | `ncd` | No clouds detected |
| CAVOK | `cavok` | Ceiling and visibility OK |
| FEW | `few` | Few (1-2 oktas) |
| SCT | `scattered` | Scattered (3-4 oktas) |
| BKN | `broken` | Broken (5-7 oktas) |
| OVC | `overcast` | Overcast (8 oktas) |
| VV | `vertical_visibility` | Vertical visibility |

`options` = all slugs above.

### Cloud type (ENUM, sensor key `cloud_coverage_type`, translation_key `cloud_coverage_type`)

| METAR | slug | en |
|-------|------|----|
| (none) | `none` | N/A |
| CB | `cumulonimbus` | Cumulonimbus |
| TCU | `towering_cumulus` | Towering Cumulus |
| CI | `cirrus` | Cirrus |
| CS | `cirrostratus` | Cirrostratus |
| CC | `cirrocumulus` | Cirrocumulus |
| AS | `altostratus` | Altostratus |
| AC | `altocumulus` | Altocumulus |
| NS | `nimbostratus` | Nimbostratus |
| SC | `stratocumulus` | Stratocumulus |
| ST | `stratus` | Stratus |
| CU | `cumulus` | Cumulus |

### Runway surface (ENUM, per-runway and `runway_states` attributes)

| code | slug | en |
|------|------|----|
| 0 | `clear_and_dry` | Clear and dry |
| 1 | `damp` | Damp |
| 2 | `wet` | Wet or water patches |
| 3 | `rime_or_frost` | Rime or frost |
| 4 | `dry_snow` | Dry snow |
| 5 | `wet_snow` | Wet snow |
| 6 | `slush` | Slush |
| 7 | `ice` | Ice |
| 8 | `compacted_snow` | Compacted snow |
| 9 | `frozen_ruts` | Frozen ruts or ridges |
| / | `not_reported` | Not reported |
| SNOCLO | `snow_closed` | Closed due to snow |
| CLRD | `cleared` | Cleared |

### Runway coverage (ENUM)

| code | slug | en |
|------|------|----|
| 0 | `cov_0` | 0% |
| 1 | `cov_lt10` | Less than 10% |
| 2 | `cov_11_25` | 11-25% |
| 3, 5 | `cov_26_50` | 26-50% |
| 4, 6 | `cov_51_75` | 51-75% |
| 7 | `cov_76_90` | 76-90% |
| 8 | `cov_91_100` | 91-100% |
| 9 | `cov_51_100` | 51-100% |
| / | `not_reported` | Not reported |

### Report type / auto (sensor key `auto_indicator`)

Prefer converting to a `binary_sensor` (auto vs manual) OR an ENUM with `options=['auto','manual']`. The current `str(True)`/`str(False)` state on the `cavok` sensor is likewise better as a `binary_sensor`.

| slug | en |
|------|----|
| `auto` | Automated report |
| `manual` | Manual report |

### Weather phenomena (NOT enum - composed token string)

State = canonical token string built from the slugs below in fixed order `intensity descriptor phenomena...`, joined deterministically (e.g. `heavy thunderstorm rain`); `clear` when none. Localized prose and the structured group list (`[{intensity, descriptor, phenomena[], recent}]`) go into `extra_state_attributes`.

Intensity: `-` -> `light`, `+` -> `heavy`, `VC` -> `vicinity`, (none) -> `moderate`.

Descriptor: MI `shallow`, PR `partial`, BC `patches`, DR `low_drifting`, BL `blowing`, SH `showers`, TS `thunderstorm`, FZ `freezing`.

Phenomena: DZ `drizzle`, RA `rain`, SN `snow`, SG `snow_grains`, IC `ice_crystals`, PL `ice_pellets`, GR `hail`, GS `small_hail`, UP `unknown_precip`, BR `mist`, FG `fog`, FU `smoke`, VA `volcanic_ash`, DU `widespread_dust`, SA `sand`, HZ `haze`, PY `spray`, PO `dust_whirls`, SQ `squalls`, FC `funnel_cloud`, SS `sandstorm`, DS `duststorm`.

Recent (RE-prefixed) phenomena keep the same phenomenon slug plus a `recent: true` flag in the attribute breakdown.

### Trend sensor (NOT enum)

`trend` is free-form forecast text (NOSIG / TEMPO ... / BECMG ...). Leave as a plain string sensor. Do not confuse it with `ATTR_TREND` (`rising`/`falling`/`veering`/`backing`/`stable`) which already lives as a slug attribute on numeric sensors and is already translated in `translations/<lang>.json`.

## Translation file structure

```
translations/en.json (and de, ru, fr):
  entity:
    sensor:
      cloud_coverage_state:
        state: { clear: "...", few: "...", scattered: "...", ... }
      cloud_coverage_type:
        state: { none: "...", cumulonimbus: "...", ... }
      runway_state:
        state_attributes:
          surface: { state: { clear_and_dry: "...", ... } }
          coverage: { state: { cov_0: "...", ... } }
```

French strings come from PR #2 (after a proofread: fix `Légere`->`Légère`, `Jusqu'a`->`Jusqu'à`, the leftover Russian `unknown`->`Neige`/correct French, distinct words for `ice_crystals` vs `freezing`, `spray`->`Embruns`).

## Migration / breaking-change discipline

Changing a sensor's state value is a one-way break: HA's recorder cannot rewrite past states, so history shows a permanent two-vocabulary split, and any automation/template/card matching the old strings (`"Light Rain"`, `"Few (1-2 oktas)"`, `"True"`) stops matching.

Steps:
1. Keep every `unique_id` and entity-description `key` unchanged. Any decomposition (e.g. splitting weather into intensity/descriptor sub-sensors) must be additive; deprecate, do not delete.
2. Apply ENUM + `translation_key` only to the finite fields above; leave `weather`, `cloud_layers`, `runway_states` (composite) and `trend` as plain strings.
3. Ship slugs and their en/de/ru/fr translation strings atomically in one release - otherwise users see raw slugs.
4. Preserve numeric sensors exactly: internal base units (km/h, km, hPa, feet), `NUMERIC_PRECISION` rounding, and the `suggested_unit_of_measurement` display path. These carry `state_class=MEASUREMENT` (long-term statistics); any value/unit/rounding drift fractures LTS.
5. Release as a major version with release notes containing the old -> new value map and the list of automations/templates/cards to update.
6. Optionally mirror the old human string into an attribute (e.g. `weather_text`) for one transitional release so users can migrate references from state to attribute.
7. Bump config-entry version only if `config_entry.data` shape changes (e.g. adding a language preference). Do not rewrite stored history records.

## Files touched in phase 2

- `const.py` - replace prose dicts with `code -> slug` maps; add `*_OPTIONS` lists for ENUM.
- `metar_parser.py` - emit slugs/tokens instead of prose for weather/clouds/runway; keep the phase-1 raw-string interface.
- `utils.py` - `parse_runway_states_from_raw` emits slugs, not prose.
- `sensor.py` - set `device_class=ENUM`, `options`, `translation_key` on finite sensors; weather state = token string, prose+breakdown in attributes; reconcile keys.
- `translations/en.json`, `de.json`, `ru.json`, new `fr.json` - `entity.sensor.<key>.state.<slug>` blocks.
- delete `translations_data.py`.
- add unit tests: raw METAR -> slug-canonical dict.
