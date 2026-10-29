# Graph Report - Thesis-2026  (2026-10-29)

## Corpus Check
- 86 files · ~52,974 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 23 file(s) not represented in the graph (top: .ino 7, .tex 6, (none) 4)

## Summary
- 972 nodes · 2300 edges · 45 communities (40 shown, 5 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 140 edges (avg confidence: 0.89)
- Token cost: 254,836 input · 0 output

## Community Hubs (Navigation)
- Spatial Simulator & Metrics
- CSI Amplitude & D-CFR
- Active Elicitation Research
- Device Registry & Window Features
- Firmware Hardware Docs
- Serial Logger Tools
- Anchor ESP-IDF Firmware
- Evaluation Harness
- Scout Mixture & Boxes
- Live CSI Dashboard
- Capture Parser & Records
- ADR Validation Sources
- k-NN Baseline
- MDN Scout Training
- Firmware Line Parsing Tests
- Relay UDP Listener Tests
- Shared Test Fixtures
- Sniper Tests
- Domain Glossary
- Radio Map
- Capture Windowing
- Particle Filter
- Wireless Capture Runbook
- ADR-0002 Algorithms
- Sniper & Fallback Rule
- Laptop Gateway & Inventory
- ADR-0003 Evaluation Protocol
- Issue Tracker & Triage
- Simulator Physics Params
- Layout Test Positions
- Scout/Sniper Modes
- Device Registry Example
- Proposed Pipeline
- Simulated Camera Device
- Simulated Plug Device
- Wireless Capture Chain
- TechHub Room Layout
- Simulated Beacon Device
- Simulated Phone Device
- Layout Zones
- Layout Anchors
- MDN Network Module
- Raw IQ to Amplitude
- Rsync Transfer Script
- Gateway Package

## God Nodes (most connected - your core abstractions)
1. `load_layout()` - 29 edges
2. `RadioMap` - 26 edges
3. `MdnScout` - 24 edges
4. `run()` - 23 edges
5. `simulate_session()` - 22 edges
6. `evaluate()` - 21 edges
7. `CONTEXT.md glossary` - 21 edges
8. `Layout` - 20 edges
9. `make_csi_line()` - 20 edges
10. `iter_logged_records()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `No CSI captured: channel had no OFDM traffic` --semantically_similar_to--> `Known signal caveats (no CSI for 802.11b, AGC)`  [INFERRED] [semantically similar]
  journal/20260717.md → firmware/README.md
- `uart_listener_2.py (make capture serial fallback)` --semantically_similar_to--> `Gateway logger (legacy wired, gateway_logger.py)`  [INFERRED] [semantically similar]
  scripts/README.md → firmware/README.md
- `DashboardState` --uses--> `CsiPayload`  [INFERRED]
  scripts/live_csi_dashboard.py → gateway/parser.py
- `payload_from_row()` --uses--> `CsiPayload`  [INFERRED]
  scripts/live_csi_dashboard.py → gateway/parser.py
- `test_legacy_captures_count_truncated_payloads_as_malformed()` --calls--> `load_session()`  [EXTRACTED]
  tests/test_parser.py → gateway/parser.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Polite WiFi active CSI elicitation on ESP32** — docs_research_active_elicitation_unassociated_devices_null_data_ack, docs_research_active_elicitation_unassociated_devices_forced_ofdm_rate, docs_research_active_elicitation_unassociated_devices_dump_ack_en, docs_research_active_elicitation_unassociated_devices_esp_wifi_80211_tx, docs_research_active_elicitation_unassociated_devices_illuminator_node, docs_research_active_elicitation_unassociated_devices_multi_anchor_attribution [EXTRACTED 1.00]
- **Shared single 2.4 GHz channel constraint** — docs_research_esp32_softap_espnow_relay_single_channel_rule, docs_research_esp32_softap_espnow_relay_esp_now, docs_research_active_elicitation_unassociated_devices_channel_parking, docs_research_passive_vs_active_sniffing_issue_13_channel_hopping, docs_research_esp32_softap_espnow_relay_home_channel [INFERRED 0.85]
- **ADR-0002 localization algorithm stack** — docs_research_2026_09_18_adr_0002_0003_validation_d_cfr, docs_research_2026_09_18_adr_0002_0003_validation_knn_baseline, docs_research_2026_09_18_adr_0002_0003_validation_mdn_scout, docs_research_2026_09_18_adr_0002_0003_validation_particle_filter, docs_research_2026_09_18_adr_0002_0003_validation_thresholds [EXTRACTED 1.00]
- **Scout -> fallback -> Sniper proposed pipeline** — docs_adr_0002_localization_algorithms_mdn_scout, docs_adr_0002_localization_algorithms_particle_filter_sniper, docs_adr_0002_localization_algorithms_fallback_rule, context_mode, docs_adr_0002_localization_algorithms_d_cfr [EXTRACTED 1.00]
- **Wireless capture data path** — context_anchor, readme_esp_now, context_relay, context_trial_network, context_gateway, context_capture [EXTRACTED 1.00]
- **Calibration and evaluation protocol** — context_beacon, docs_adr_0003_calibration_and_evaluation_protocol_reference_grid, docs_adr_0003_calibration_and_evaluation_protocol_held_out_test_positions, docs_adr_0003_calibration_and_evaluation_protocol_separate_occasions, docs_adr_0003_calibration_and_evaluation_protocol_cross_device_trial, docs_adr_0003_calibration_and_evaluation_protocol_success_criteria [EXTRACTED 1.00]
- **Wireless capture chain: Anchor, Relay, Beacon, UDP listener** — firmware_readme_anchor, firmware_readme_relay, firmware_readme_beacon, scripts_readme_relay_udp_listener, firmware_readme_wireless_chain [EXTRACTED 1.00]
- **Proposed pipeline: Scout bbox, Sniper particle filter, fallback rule, stability score** — journal_20261002_mdn_scout, journal_20261002_sniper_particle_filter, journal_20261002_fallback_rule, journal_20261002_stability_score, journal_20261002_proposed_localizer [EXTRACTED 1.00]
- **Localizers sharing estimate() interface evaluated by harness** — journal_20261002_knn_baseline, journal_20261002_mdn_scout, journal_20261002_proposed_localizer, journal_20261002_evaluation_harness [INFERRED 0.85]

## Communities (45 total, 5 thin omitted)

### Community 0 - "Spatial Simulator & Metrics"
Cohesion: 0.06
Nodes (49): metrics(), _beacon(), check_coverage(), csi_fingerprint(), Device, _image_sources(), Layout, load_layout() (+41 more)

### Community 1 - "CSI Amplitude & D-CFR"
Cohesion: 0.08
Nodes (43): aggregate(), dcfr(), dcfr_stability(), hw_to_usable_indices(), is_valid_csi(), normalize(), remap_hw64_to_usable(), valid_spectra() (+35 more)

### Community 2 - "Active Elicitation Research"
Cohesion: 0.06
Nodes (50): channel_filter_en = false, wifi_csi_config_t, Target channel parking requirement, DeviceRegistry (gateway), Active elicitation of RSSI/CSI from unassociated hidden devices, dump_ack_en (CSI of ACK frames), esp-idf issue #10668 (raw TX restrictions, RTS suppression), esp-idf issue #19062 (CSI from ACK via dump_ack_en) (+42 more)

### Community 3 - "Device Registry & Window Features"
Cohesion: 0.07
Nodes (34): usable_subcarriers(), DeviceEntry, DeviceRegistry, build_window_features(), _anchor_dict(), feature_to_dict(), _json_default(), _percentiles() (+26 more)

### Community 4 - "Firmware Hardware Docs"
Cohesion: 0.06
Nodes (47): anchor_fw ESP-IDF project CMakeLists, anchor main component registration (main, sniffer, csv_out, wifi_conn, udp_out), Firmware README (Anchors, Relay, Beacon), Anchor (passive RSSI+CSI sniffer), Beacon (steady HT MCS0 broadcast transmitter), Gateway logger (legacy wired, gateway_logger.py), CSI/STAT line output format, Relay (ESP-NOW aggregator to UDP/serial) (+39 more)

### Community 5 - "Serial Logger Tools"
Cohesion: 0.08
Nodes (20): check_one(), main(), AnchorLogger, main(), parse_port(), generate(), main(), make_csi_template() (+12 more)

### Community 6 - "Anchor ESP-IDF Firmware"
Cohesion: 0.07
Nodes (14): csv_out_init(), csv_out_submit(), emit(), format_record(), format_stats(), writer_task(), app_main(), csi_rx_cb() (+6 more)

### Community 7 - "Evaluation Harness"
Cohesion: 0.10
Nodes (12): bbox_metrics(), evaluate(), _locate(), main(), mode_metrics(), preprocess_session(), run_baseline(), read_jsonl() (+4 more)

### Community 8 - "Scout Mixture & Boxes"
Cohesion: 0.09
Nodes (11): bbox(), Mixture, scout_input(), _random_mixture(), _rssi_at(), test_bbox_contains_the_mixture_mean_and_stays_inside_the_room(), test_bbox_holds_the_clipped_mean_when_the_mean_is_outside_the_room(), test_bbox_of_one_gaussian_is_its_95_percent_disc() (+3 more)

### Community 9 - "Live CSI Dashboard"
Cohesion: 0.09
Nodes (10): legacy_row_to_line(), build_parser(), clean_amplitudes(), DashboardState, main(), refresh(), moving_average_rows(), newest_capture() (+2 more)

### Community 10 - "Capture Parser & Records"
Cohesion: 0.15
Nodes (13): expand_inputs(), iter_logged_records(), load_session(), _parse_host_iso(), AnchorFeature, CsiRecord, ParseStats, StatRecord (+5 more)

### Community 11 - "ADR Validation Sources"
Cohesion: 0.12
Nodes (17): Ablation #29 (add raw normalized amplitude + Pearson arm), ADR-0002 Localization Algorithms, ADR-0003 Calibration and Evaluation Protocol, Bishop, Mixture Density Networks (1994), ADR-0002/0003 Validation Against Primary Sources, ESP32 CSI facts (LLTF 64 entries, rx_ctrl.rssi, first_word_invalid), FILA (Wu et al., CSI-Based Indoor Localization, TPDS 2012), Ghany et al. 2020 CSI-vs-RSSI robustness (+9 more)

### Community 12 - "k-NN Baseline"
Cohesion: 0.19
Nodes (11): feature_vector(), KnnLocalizer, zscored_rssi(), test_estimate_is_inverse_distance_weighted(), test_feature_blocks_have_equal_weight(), test_insufficient_window_gives_no_estimate(), test_missing_anchor_is_floor_imputed(), test_missing_anchor_never_looks_stronger_than_a_present_one() (+3 more)

### Community 13 - "MDN Scout Training"
Cohesion: 0.16
Nodes (9): augmented_samples(), main(), MdnScout, run_scout(), ScoutConfig, run_proposed(), test_loss_decreases_on_a_toy_set(), test_run_scout_on_the_default_simulator() (+1 more)

### Community 14 - "Firmware Line Parsing Tests"
Cohesion: 0.23
Nodes (17): CsiPayload, parse_firmware_line(), StatPayload, make_csi_line(), make_logged_row(), _legacy_capture(), test_bad_mac_rejected(), test_bad_n_sub_rejected() (+9 more)

### Community 15 - "Relay UDP Listener Tests"
Cohesion: 0.13
Nodes (8): test_capture_row_is_tailable_by_the_matlab_dashboard(), test_csi_line_for_new_anchor_opens_file_and_writes_row(), open_anchor_file(), test_heartbeat_line_is_counted_and_not_written_to_any_file(), test_relay_heartbeat_with_diagnostic_fields_is_counted_not_written(), test_stat_line_for_known_anchor_reuses_existing_file_no_new_header(), test_truncated_csi_line_with_no_anchor_field_is_skipped_not_raised(), test_unrecognized_line_is_skipped_not_raised()

### Community 16 - "Shared Test Fixtures"
Cohesion: 0.15
Nodes (11): csi_line(), _default_amps(), make_stat_line(), stat_line(), _payload(), _row(), test_clean_amplitudes_fills_zero_bins_with_mean_of_rest(), test_moving_average_rows_matches_centred_movmean() (+3 more)

### Community 17 - "Sniper Tests"
Cohesion: 0.22
Nodes (12): _obs(), _ready_window(), _stored(), _StubScout, test_a_missing_anchor_does_not_stop_the_sniper(), test_each_condition_triggers_fallback_with_the_scout_estimate(), test_each_fallback_condition_alone_makes_an_anchor_not_ready(), test_insufficient_window_has_no_estimate() (+4 more)

### Community 18 - "Domain Glossary"
Cohesion: 0.18
Nodes (15): CONTEXT.md glossary, Beacon, Calibration session, Capture, Radio map, Record, Reference point, Test position (+7 more)

### Community 19 - "Radio Map"
Cohesion: 0.21
Nodes (10): AnchorFingerprint, build_radio_map(), RadioMap, ReferencePoint, _point(), radio_map(), test_build_gives_one_entry_per_reference_point(), test_build_ignores_other_devices() (+2 more)

### Community 20 - "Capture Windowing"
Cohesion: 0.24
Nodes (10): assign_windows(), is_sufficient(), rec(), test_boundary_record_lands_in_later_window(), test_deterministic_t0(), test_empty_input(), test_macs_grouped_independently(), test_min_pkts_demotes_anchor() (+2 more)

### Community 21 - "Particle Filter"
Cohesion: 0.21
Nodes (4): ParticleFilter, systematic_resample(), _unit(), test_systematic_resample_keeps_the_weight_proportions()

### Community 22 - "Wireless Capture Runbook"
Cohesion: 0.16
Nodes (14): CLAUDE.md agent instructions, Trial network, Wireless capture runbook, ignore_macs filter, MP700 settings (ch 11 fixed, AP isolation off, .197 reserved), Troubleshooting guide, Repo README, journal/ dated work log (+6 more)

### Community 23 - "ADR-0002 Algorithms"
Cohesion: 0.27
Nodes (11): ADR-0002 Localization algorithms, Ablation table (#29), D-CFR (differenced CFR amplitude), Within-window D-CFR stability (median pairwise Pearson rho), 2026-08-28 two-anchor capture, Device heterogeneity, Kjaergaard & Munk 2008, k-NN baseline (k=3, IDW) (+3 more)

### Community 24 - "Sniper & Fallback Rule"
Cohesion: 0.27
Nodes (7): _fmt(), format_comparison(), format_table(), main(), ready_anchors(), sniper_ready(), SniperConfig

### Community 25 - "Laptop Gateway & Inventory"
Cohesion: 0.24
Nodes (9): ADR-0001 Laptop Gateway replaces Pi, Raspberry Pi (retired), File inventory, live_csi_dashboard.py (live), realtime_csi_dashboard.m (legacy), rsync_data_transfer.sh (legacy, Pi), uart_listener_2.py (live), Laptop static IP 192.168.0.197 (+1 more)

### Community 26 - "ADR-0003 Evaluation Protocol"
Cohesion: 0.20
Nodes (8): 2026-09-18 ADR-0002/0003 validation research, RADAR (Bahl & Padmanabhan 2000), ADR-0003 Calibration and evaluation protocol, Horus (Youssef & Agrawala 2005), RADAR tech report MSR-TR-2000-12, ~1 m Reference grid, thesis/references.bib, Window length as Trial parameter

### Community 27 - "Issue Tracker & Triage"
Cohesion: 0.20
Nodes (11): Issue tracker: GitHub, gh CLI conventions, PRs as triage surface (no), Wayfinding operations (map / child tickets / blocking), Triage labels, needs-info, needs-triage, ready-for-agent (+3 more)

### Community 28 - "Simulator Physics Params"
Cohesion: 0.18
Nodes (11): physics, csi_mean_amplitude, csi_noise, path_loss_exponent, phase_wavelength_m, reflection_order, rssi_at_1m_dbm, rssi_jitter_db (+3 more)

### Community 29 - "Layout Test Positions"
Cohesion: 0.18
Nodes (11): test_positions, P1, P10, P2, P3, P4, P5, P6 (+3 more)

### Community 30 - "Scout/Sniper Modes"
Cohesion: 0.27
Nodes (10): Mode, Scout, Sniper, Bishop 1994 Mixture Density Networks, FILA (Wu et al. 2013), MDN Scout (K=3 diagonal Gaussians), Particle-filter Sniper (w = prod exp(rho/sigma)), Qian et al. 2019 (+2 more)

### Community 31 - "Device Registry Example"
Cohesion: 0.20
Nodes (9): cooperation, visibility, default_role, devices, attrs, label, mac, role (+1 more)

### Community 33 - "Simulated Camera Device"
Cohesion: 0.20
Nodes (10): burst_mean, gain, mac, mode, position, rate_hz, role, tilt (+2 more)

### Community 34 - "Simulated Plug Device"
Cohesion: 0.20
Nodes (10): plug, burst_mean, gain, mac, mode, position, rate_hz, role (+2 more)

### Community 35 - "Wireless Capture Chain"
Cohesion: 0.36
Nodes (9): Anchor, Gateway, Relay, anchor_arduino_wireless.ino (live), firmware relay/relay.ino (live), relay_udp_listener.py (live), Relay HEARTBEAT lines, Wireless chain Anchor->Relay->MP700->Gateway (+1 more)

### Community 36 - "TechHub Room Layout"
Cohesion: 0.25
Nodes (7): devices, grid, margin_m, spacing_m, room, height_m, width_m

### Community 37 - "Simulated Beacon Device"
Cohesion: 0.25
Nodes (8): gain, mac, mode, rate_hz, role, tilt, tx_offset_db, beacon

### Community 38 - "Simulated Phone Device"
Cohesion: 0.25
Nodes (8): phone, gain, mac, mode, rate_hz, role, tilt, tx_offset_db

### Community 39 - "Layout Zones"
Cohesion: 0.29
Nodes (7): zones, Z1, Z2, Z3, Z4, Z5, Z6

### Community 40 - "Layout Anchors"
Cohesion: 0.40
Nodes (5): anchors, A1, A2, A3, A4

## Knowledge Gaps
- **45 isolated node(s):** `gateway`, `WKNN / Torres-Sospedra et al. 2015`, `Bishop, Mixture Density Networks (1994)`, `Qian et al., Convolutional Mixture Density RNN (2019)`, `Ghany et al. 2020 CSI-vs-RSSI robustness` (+40 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 317 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Gateway laptop` connect `Active Elicitation Research` to `Serial Logger Tools`?**
  _High betweenness centrality (0.118) - this node is a cross-community bridge._
- **Are the 10 inferred relationships involving `RadioMap` (e.g. with `KnnLocalizer` and `augmented_samples()`) actually correct?**
  _`RadioMap` has 10 INFERRED edges - model-reasoned connections that need verification._
- **What connects `gateway`, `WKNN / Torres-Sospedra et al. 2015`, `Bishop, Mixture Density Networks (1994)` to the rest of the system?**
  _45 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Spatial Simulator & Metrics` be split into smaller, more focused modules?**
  _Cohesion score 0.05864197530864197 - nodes in this community are weakly interconnected._
- **Should `CSI Amplitude & D-CFR` be split into smaller, more focused modules?**
  _Cohesion score 0.08050655811849841 - nodes in this community are weakly interconnected._
- **Should `Active Elicitation Research` be split into smaller, more focused modules?**
  _Cohesion score 0.058469945355191254 - nodes in this community are weakly interconnected._
- **Should `Device Registry & Window Features` be split into smaller, more focused modules?**
  _Cohesion score 0.06957047791893527 - nodes in this community are weakly interconnected._