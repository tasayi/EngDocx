---
title: Satellite Thermal Control Subsystem Specification
document_number: ENG-TCS-2026
revision: B
author: Thermal & Fluids Engineering Directorate
date: 2026-11-01
---

# 1. Executive Summary & Thermal Environment

This technical specification establishes the governing requirements, heat flux models, telemetry bus architectures, and operational temperature limits for the satellite Thermal Control Subsystem (TCS).

The space thermal environment in low Earth orbit (LEO) is defined by severe cyclic radiative extremes:

$$
q_{\text{net}} = q_{\text{solar}} + q_{\text{albedo}} + q_{\text{Earth}} - \epsilon \sigma T^4
$$

Where the Stefan-Boltzmann constant is defined as: $\sigma = 5.670374 \times 10^{-8} \text{ W}/(\text{m}^2 \cdot \text{K}^4)$.

## 1.1 Direct Solar and Albedo Radiative Modeling

Incident solar flux on the sun-tracking facets is modeled as:

$$
Q_{\text{solar}} = \alpha_s \cdot S_0 \cdot A \cos(\theta)
$$

Where:
- $\alpha_s$: Solar absorptance ($0.18 \le \alpha_s \le 0.88$)
- $S_0$: Solar irradiance constant ($1361 \text{ W/m}^2$)
- $A$: Surface cross-sectional area ($\text{m}^2$)
- $\theta$: Solar incidence angle relative to the facet normal vector

# 2. Sensor Telemetry Bus Architecture

Telemetry acquisition is achieved via high-precision resistance temperature detectors (RTDs) and negative temperature coefficient (NTC) thermistors interconnected over a fault-tolerant differential bus.

@figure FIG-001
  caption: "Thermal Sensor Telemetry Bus Architecture and Thermistor Placement"
  width: "140mm"
@end

@section
  orientation: landscape
  page: A4
  columns: 2
@end

# 3. Subsystem Thermal Limits & Mode Operational Matrix

The satellite operational flight envelope requires strict thermal boundary control across all operational modes:

| Subsystem Assembly | Minimum Survival (°C) | Minimum Operating (°C) | Maximum Operating (°C) | Maximum Survival (°C) |
|---|---|---|---|---|
| OBC & Avionics Stack | -20 | -10 | +50 | +60 |
| Battery Pack Cells | -10 | 0 | +30 | +45 |
| Solar Array Panels | -120 | -100 | +90 | +110 |
| S-Band Transceiver | -30 | -20 | +55 | +70 |
| Monopropellant Hydrazine Tank | +5 | +10 | +40 | +50 |

## 3.1 Heater Power Budget Allocations

Active thermal control employs pulse-width modulated (PWM) kapton film heaters placed on fluid lines and propellent tanks:

| Thermal Zone | Resistance (Ω) | Bus Voltage (V) | Peak Duty Cycle | Average Power (W) |
|---|---|---|---|---|
| Zone 1: Tank Bulkhead | 28.5 | 28.0 | 45% | 12.4 |
| Zone 2: Hydrazine Lines | 56.0 | 28.0 | 30% | 4.2 |
| Zone 3: Optical Payload | 38.0 | 28.0 | 25% | 5.2 |

@section
  orientation: portrait
  page: A4
  columns: 1
@end

# 4. Conductive Heat Transfer Formulations

Heat transfer through structural standoffs and conductive bolted joints is evaluated using 1D thermal resistance networks:

$$
R_{\text{cond}} = \frac{L}{k \cdot A_c}
$$

For multi-layer insulation (MLI) blankets with $N$ reflective radiation shields, the effective emittance is expressed as:

$$
\epsilon^* = \frac{1}{\frac{N+1}{2} \cdot \left(\frac{2}{\epsilon_{\text{shield}}} - 1\right)}
$$

@pagebreak

# 5. Verification & Acceptance Criteria

Thermal balance chamber testing shall demonstrate that all flight temperatures remain within designated operational limits under both hot-case solar maximum and cold-case eclipse minimum conditions with a minimum margin of $\pm 5^\circ\text{C}$.

