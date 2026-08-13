# The rain alert

What actually runs in the house: a Home Assistant automation that sends a
Telegram message when rain looks likely. This page documents the rule, what it
was measured at, and the rule it replaces.

## The rule

```
pressure_anomaly < −3 hPa   AND   outdoor_humidity > 75 %
```

where `pressure_anomaly` is the current barometer reading minus its own median
over the previous 30 days.

Two things about it are worth stating plainly, because both contradict how this
project has modelled rain until now.

**It leads with pressure, not humidity dynamics.** Every model in `MODELS` is
built on the dew-point-spread derivative, which measures at ROC AUC 0.49 over
49,200 hours — chance. Absolute pressure reaches 0.75. See
[MODELS.md](MODELS.md) and `plans/model-improvements.md`.

**It uses no dew-point spread at all.** A `spread < 4 °C` term was offered to
the threshold search and rejected: adding it changed precision by 0.002 and cost
recall. The spread is not useless, but on top of pressure and humidity it adds
nothing.

### Why an anomaly rather than an absolute pressure

The barometer sits at roughly 220 m, where station pressure has a median of
989.6 hPa and never exceeds 1001. Any rule written against sea-level figures —
"below 1000 hPa means low" — is true here almost all the time. Subtracting the
station's own recent median removes the elevation offset without needing to know
the elevation, and tracks the seasonal drift for free.

## What it scores

Ground truth is Open-Meteo precipitation ≥ 0.1 mm/h; the target is rain in any of
the next three hours. Measured on two independent datasets:

| | precision | recall | alerts/day | lift over base rate |
|---|:---:|:---:|:---:|:---:|
| **Deployed rule** (local sensors, 31 d) | 0.404 | 0.109 | 0.90 | 1.72× |
| **This rule** (local sensors, 31 d) | 0.789 | 0.171 | 0.26 | 3.36× |
| **Deployed rule** (reanalysis, 17 mo held out) | 0.401 | 0.096 | 1.04 | 1.47× |
| **This rule** (reanalysis, 17 mo held out) | 0.555 | 0.397 | 0.30 | 2.03× |

The rule is better on all three axes at once — more of its alerts are right, it
catches more rain, and it interrupts you less often. That combination is
unusual enough to be worth double-checking, which is why both datasets are
quoted.

**Take the reanalysis row as the honest estimate.** The local sample covers 31
days with 175 rain events, and its precision of 0.789 is almost certainly
flattering; the 17-month held-out figure of 0.555 is measured over 12,294 hours
and is the number to expect. Both agree on the direction and on the ordering
against the deployed rule.

### Threshold choice

| anomaly threshold | precision | recall | alerts/day |
|---|:---:|:---:|:---:|
| < −1 hPa | 0.519 | 0.488 | 0.40 |
| < −2 hPa | 0.537 | 0.449 | 0.35 |
| **< −3 hPa** | **0.555** | **0.397** | **0.30** |
| < −4 hPa | 0.566 | 0.347 | 0.29 |

(reanalysis, held out.) −3 is chosen over −1 because an alert acted on by a
person has to be worth believing: the extra 0.09 of recall at −1 costs a third
more interruptions. Move it to −1 if missing rain matters more to you than being
interrupted.

## Implementation

Three helpers and one automation. The 30-day median comes from the `statistics`
integration, so no custom code is needed.

```yaml
# 1. The station's own 30-day normal.
#    sampling_size must be large: the barometer reports every few minutes, and
#    the default of 20 samples would cover about an hour, not a month.
sensor:
  - platform: statistics
    name: "Pressure median 30d"
    entity_id: sensor.filtered_pressure
    state_characteristic: median
    max_age:
      days: 30
    sampling_size: 5000

# 2. How far below normal we are, in hPa.
template:
  - sensor:
      - name: "Pressure anomaly"
        unique_id: pressure_anomaly
        unit_of_measurement: "hPa"
        state_class: measurement
        state: >
          {% set now = states('sensor.filtered_pressure') | float(none) %}
          {% set normal = states('sensor.pressure_median_30d') | float(none) %}
          {% if now is none or normal is none %}
            unknown
          {% else %}
            {{ (now - normal) | round(2) }}
          {% endif %}

# 3. The rule itself. delay_on debounces a brief dip; delay_off is the re-arm
#    interval, so a single weather system produces one alert rather than a
#    stream of them as the condition flickers around the threshold.
  - binary_sensor:
      - name: "Rain likely"
        unique_id: rain_likely
        device_class: moisture
        delay_on: "00:20:00"
        delay_off: "02:00:00"
        state: >
          {{ states('sensor.pressure_anomaly') | float(99) < -3
             and states('sensor.datchik_klimata_vlazhnost') | float(0) > 75 }}
```

```yaml
# The automation fires on the transition into the state, never while it holds.
alias: Rain likely notification
triggers:
  - trigger: state
    entity_id: binary_sensor.rain_likely
    from: "off"
    to: "on"
actions:
  - action: telegram_bot.send_message
    data:
      entity_id: notify.telegram_bot_kastus
      message: >-
        🌧️ Chutka mažlivy doždž u najbližšyja 3 hadziny.

        Cisk {{ states('sensor.pressure_anomaly') }} hPa niža za narmalny,
        vilhotnaść {{ states('sensor.datchik_klimata_vlazhnost') }}%.
mode: single
```

### Notes on deployment

- `sensor.pressure_median_30d` needs 30 days of history before it means
  anything. Home Assistant's long-term statistics for `sensor.filtered_pressure`
  begin 2026-07-12, so the median is trustworthy from mid-August onward. Until
  then the anomaly reads as a smaller departure than it should and the rule
  under-fires — which is the safe direction.
- `delay_off: 2h` is the re-arm interval. Without it the binary sensor chatters
  whenever the anomaly sits near −3, and each flicker is a message.
- The old automation triggered directly on `sensor.outside_dew_point_spread`.
  Remove it when this one goes in, or you will get both.

## The rule this replaces

```yaml
# Deployed until 2026-08-14 — kept here as the reference to beat.
triggers:
  - trigger: numeric_state
    entity_id: sensor.outside_dew_point_spread
    below: 4
    for: {minutes: 5}
conditions:
  - condition: numeric_state
    entity_id: sensor.outside_dew_point_spread_trend
    below: -0.5
```

Its measured recall is 0.096–0.109: it missed about nine rain events in ten, and
around 60% of the alerts it did send were wrong. The trend term is the weakest
signal available, and firing on a `numeric_state` crossing with no re-arm made
it about one alert per day.

## Caveats

- Ground truth is Open-Meteo, which agrees with Meteostat at only κ = 0.495. A
  meaningful share of the measured error belongs to the yardstick rather than to
  the rule; a local rain gauge would settle it.
- The thresholds were fitted on 2021-01 → 2025-03 and measured on 2025-03 →
  2026-08. They are not tuned to the local barometer, which has too little
  history for that yet — re-check them once a full year of local pressure has
  accumulated.
- This is a rule, deliberately. The fitted model in `analysis/learned.py` scores
  ROC AUC 0.753 against this rule's inputs and would do better, but it cannot
  run as a Home Assistant template; deploying it needs the backend to serve
  predictions.

---

_Measured 2026-08-14. Reproduce with `data/archive/ha_hourly.csv` and the
Open-Meteo archive; see `plans/model-improvements.md` for the method._
